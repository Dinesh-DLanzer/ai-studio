"""Role chains: run one purpose (chat, vision, image, video ...) through its ordered list of models, with fallback.  Standard library only.

RoleRunner.run(role, call, ...) tries each model of the role's chain in order and returns on the first success.
Outcome handling for one model:
  Retryable (429, 5xx, timeout, empty answer) -> retry up to policy["retries"] times with backoff, then try the next model.
  AuthError                                   -> the provider is marked UNHEALTHY for a while (skipped later), try the next model.
  Rejected / NotFound / Unsupported           -> try the next model.
All attempts are kept; if every model fails ONE ChainError lists them all.
Cost rule: when `approved_price` is given, a model whose price is unknown or higher is never used silently; if nothing cheaper works the
runner raises NeedsNewApproval. Vision may use an unknown price only for the exact approved provider/model, never an unknown fallback.
Video: submit -> poll -> download.  A job that was ACCEPTED and then fails is NOT retried on another model (money may be spent); a timeout
returns {"status":"pending", "job": ...} so `sync` can finish it later.
"""
import shutil
import time

from aistudio import approvals, catalog as catalog_mod
from aistudio.providers import config as cfg
from aistudio.providers.base import AuthError, ProviderError, Retryable, scrub

UNHEALTHY_SECONDS = 600


class ChainError(Exception):
    def __init__(self, message, attempts=(), code="all_failed"):
        super().__init__(message)
        self.attempts, self.code = list(attempts), code


class NeedsNewApproval(ChainError):
    def __init__(self, message, entry, price, attempts=()):
        super().__init__(message, attempts, "needs_approval")
        self.entry, self.price = entry, price


class GrantRequired(ChainError):
    def __init__(self, message="a human approval grant is required for this paid operation"):
        super().__init__(message, code="grant_required")


class Health:
    def __init__(self, clock=time.time):
        self.clock, self.bad, self.tests = clock, {}, {}

    def mark_unhealthy(self, pid, reason):
        self.bad[pid] = (self.clock() + UNHEALTHY_SECONDS, reason)

    def unhealthy(self, pid):
        until = self.bad.get(pid)
        if until and until[0] > self.clock():
            return until[1]
        self.bad.pop(pid, None)
        return None

    def clear(self, pid):
        self.bad.pop(pid, None)

    def record_test(self, pid, result):
        self.tests[pid] = {**result, "checked_at": self.clock()}
        if result.get("ok"):
            self.clear(pid)


class RoleRunner:
    def __init__(self, settings_dir, secrets, pricing, transport=None, adapter_factory=None, fake_mode=lambda: False,
                 health=None, sleep=time.sleep, poll_seconds=10, clock=time.time, trust_transport=False, chain_override=None, fake_for=None):
        self.dir, self.secrets, self.pricing, self.transport = settings_dir, secrets, pricing, transport
        self.factory, self.fake_mode, self.health, self.sleep, self.poll_seconds, self.clock = adapter_factory, fake_mode, health or Health(clock), sleep, poll_seconds, clock
        self.trust_transport, self.chain_override = trust_transport, chain_override     # tests / env locks
        self.catalog = None             # aistudio.catalog.Catalog, set by the Workspace; lets run() skip models lacking a required feature
        self.fake_for = fake_for        # optional (role, project_dir) -> bool: lets one project run some roles on the fake provider

    def _fake(self, role, project_dir=None):
        return self.fake_for(role, project_dir) if self.fake_for else self.fake_mode()

    def _grant(self, role, project_dir, grant, first=None):
        """Require and redeem a Grant whenever the configured role can call a non-free card."""
        if grant is not None:
            if not isinstance(grant, approvals.Grant) or project_dir is None:
                raise GrantRequired("invalid approval grant")
            try:
                return approvals.redeem(project_dir, grant, role)
            except approvals.ApprovalError as e:
                raise GrantRequired(str(e)) from None
        entries = self.resolve(role, project_dir) + ([first] if first else [])
        paid = [e for e in entries if e.get("problem") is None and not self.pricing.is_free(e.get("card"))]
        if paid:
            raise GrantRequired(f"a human approval grant is required before calling {role}")
        return None

    # -------------------------------------------------------------- resolving
    def providers(self):
        return {p["id"]: p for p in cfg.load_providers(self.dir)}

    def adapter(self, provider):
        if self.factory:
            return self.factory(provider)
        return cfg.build_adapter(provider, self.secrets, self.transport)

    def _usable(self, p):
        """None if the provider can be called, else a short reason."""
        if p is None:
            return "provider was removed"
        if not p.get("enabled", True):
            return "provider is disabled"
        if p["type"] == "fake":
            return None
        binary = cfg.needs_binary(p["type"])
        if binary:
            return None if shutil.which(binary) else f"{binary} CLI is not installed"
        if not self.trust_transport and not self.secrets.has(p.get("secret_ref") or p["id"]) and not (p["type"] == "custom" and p.get("base_url")):
            return "not signed in" if cfg.PROVIDER_TYPES[p["type"]].get("auth_type") == "oauth" else "no API key"
        return None

    def resolve(self, role, project_dir=None, configured=False):
        """Entries for the chain: {"provider","ptype","model","problem","card","index"}; problem is None when the entry can be called."""
        if not configured and self._fake(role, project_dir):      # test mode runs everything on the built-in test provider; `configured` shows the real chain anyway
            fp = {"id": "fake", "type": "fake", "label": "Built-in test", "enabled": True}
            model = "fake/" + {"chat": "llm", "verify": "llm", "vision": "vision", "image": "image", "video": "video",
                                "tts": "audio", "music": "audio", "sfx": "audio", "lipsync": "audio", "transcribe": "audio"}[role]
            return [{"provider": fp, "ptype": "fake", "model": model, "problem": None, "card": self.pricing.card("fake", "fake", model), "index": 0}]
        provs = self.providers()
        chain = (self.chain_override(role) if self.chain_override else None) or cfg.effective_roles(self.dir, project_dir)["roles"][role]["chain"]
        out = []
        for i, ref in enumerate(chain):
            p = provs.get(ref.get("provider"))
            problem = self._usable(p)
            if problem is None and cfg.ROLE_CAPABILITY[role] not in cfg.capabilities_of(p["type"]):
                problem = f"cannot do {cfg.ROLE_CAPABILITY[role]}"
            out.append({"provider": p or {"id": ref.get("provider"), "type": "?", "label": ref.get("provider")}, "ptype": (p or {}).get("type", "?"),
                        "model": ref["model"], "problem": problem, "index": i,
                        "card": self.pricing.card(ref.get("provider"), (p or {}).get("type"), ref["model"]) if p else None})
        return out

    def entry_for(self, role, provider_id, model, project_dir=None):
        """A chain-shaped entry for a model that is not (or not first) in the chain, or None when its provider cannot be used for this role."""
        p = self.providers().get(provider_id)
        if p is None or self._usable(p) or cfg.ROLE_CAPABILITY[role] not in cfg.capabilities_of(p["type"]):
            return None
        return {"provider": p, "ptype": p["type"], "model": model, "problem": None, "index": -1, "card": self.pricing.card(p["id"], p["type"], model)}

    def policy(self, role, project_dir=None):
        return cfg.effective_roles(self.dir, project_dir)["roles"][role]["policy"]

    # -------------------------------------------------------------- the generic runner
    def run(self, role, call, project_dir=None, allow=None, approved_price=None, price_of=None, retry_after_submit=False, approved_unknown_entry=None, first=None, required=None):
        """call(adapter, model) -> result. Returns {"result", "provider", "model", "card", "attempts"}.
        approved_unknown_entry is an approved (provider id, model) pair.
        first is an entry tried before the chain (a shot's own model); required is a request-feature dict: entries whose profile lacks one are skipped, never degraded.
        """
        entries = self.resolve(role, project_dir)
        if first and not self._fake(role, project_dir):
            entries = [first] + [e for e in entries if (e["provider"]["id"], e["model"]) != (first["provider"]["id"], first["model"])]
        if not entries:
            raise ChainError(f"No model is set for '{role}'. Add a provider and pick a model in Settings.", code="unconfigured")
        pol = self.policy(role, project_dir) if not self._fake(role, project_dir) else cfg.default_policy(role)
        attempts, needs_approval = [], None
        sick = [e for e in entries if e["problem"] is None and self.health.unhealthy(e["provider"]["id"])]
        for e in entries:
            who = f"{e['provider'].get('label') or e['provider']['id']}:{e['model']}"
            if e["problem"]:
                attempts.append({"who": who, "error": e["problem"], "skipped": True})
                continue
            if required and self.catalog:
                why = catalog_mod.missing(self.catalog.profile(e["provider"]["id"], e["ptype"], e["model"], e["card"]), e["ptype"], required)
                if why:
                    attempts.append({"who": who, "error": f"skipped: {why}", "skipped": True})
                    continue
            if allow:
                ok, why = allow(e)
                if not ok:
                    attempts.append({"who": who, "error": why, "skipped": True})
                    continue
            if approved_price is not None:
                price = price_of(e) if price_of else None
                if price is None and (e["provider"]["id"], e["model"]) != approved_unknown_entry:
                    attempts.append({"who": who, "error": "price unknown (set a price in Settings)", "skipped": True})
                    needs_approval = needs_approval or (e, price)
                    continue
                if price is not None and price > approved_price + 1e-9:
                    attempts.append({"who": who, "error": f"costs ${price:.3f} (more than the approved ${approved_price:.3f})", "skipped": True})
                    needs_approval = needs_approval or (e, price)
                    continue
            bad = self.health.unhealthy(e["provider"]["id"])
            if bad and len(sick) < len([x for x in entries if x["problem"] is None]):
                attempts.append({"who": who, "error": f"skipped, provider unhealthy ({bad})", "skipped": True})
                continue
            adapter = self.adapter(e["provider"])
            tries = 1 + int(pol.get("retries", 1))
            for n in range(tries):
                try:
                    res = call(adapter, e["model"])
                    return {"result": res, "provider": e["provider"]["id"], "ptype": e["ptype"], "model": e["model"], "card": e["card"], "attempts": attempts}
                except Retryable as ex:
                    attempts.append({"who": who, "error": scrub(ex, adapter.secret)[:200], "retry": n + 1 < tries})
                    if n + 1 < tries:
                        self.sleep(min(2 ** n, 8))
                except AuthError as ex:
                    self.health.mark_unhealthy(e["provider"]["id"], "key rejected or out of credit")
                    attempts.append({"who": who, "error": scrub(ex, adapter.secret)[:200]})
                    break
                except _Stop as ex:                       # video job accepted then failed: do not move to another model
                    ex.attempts = attempts + [{"who": who, "error": ex.args[0]}]
                    raise
                except ProviderError as ex:                  # Rejected, NotFound, Unsupported and anything else a provider raises
                    attempts.append({"who": who, "error": scrub(ex, adapter.secret)[:200]})
                    break
        if needs_approval:
            e, price = needs_approval
            price_text = "price unknown (set a price in Settings)" if price is None else f"${price:.3f}"
            raise NeedsNewApproval(f"No '{role}' model succeeded within the approved price. Next choice: {e['model']} at {price_text}; new approval required.", e, price, attempts)
        raise ChainError(f"All '{role}' models failed: " + " | ".join(f"{a['who']} -> {a['error']}" for a in attempts), attempts)

    # -------------------------------------------------------------- conveniences
    def _cost(self, role, out, card, usage=None, extra=None):
        reported = out.get("cost")
        computed = None
        try:
            if role in ("chat", "verify", "vision"):
                computed = self.pricing.text_cost(card, usage or out.get("usage"))
            elif role == "image":
                computed = self.pricing.image_price(card, (extra or {}).get("refs", 0))
            elif role == "video" and extra:
                computed = self.pricing.video_price(card, extra["seconds"], extra.get("resolution", "720p"), extra.get("audio", False), extra.get("refs", 0))
        except (KeyError, TypeError, ValueError):
            computed = None
        if computed is None and reported is None and card and not self.pricing.is_free(card) and role not in ("chat", "verify", "vision"):
            quoted = (extra or {}).get("quoted")
            if quoted is not None:
                return float(quoted), "estimated"
        return self.pricing.actual_cost(reported, computed)

    def chat(self, role, messages, opts=None, project_dir=None, allow=None, tools=None):
        def _call(a, m):
            if tools is not None:
                try:
                    return a.chat_tools(m, messages, tools, opts)
                except pbase.Unsupported:
                    pass
            return a.chat(m, messages, opts)
        r = self.run(role, _call, project_dir, allow)
        out = r["result"]
        cost, src = self._cost(role, out, r["card"])
        return {**out, "cost": cost, "cost_source": src, "provider": r["provider"], "attempts": r["attempts"]}

    def vision(self, prompt, images, opts=None, project_dir=None, allow=None, *, grant=None, allow_paid=False):
        grant = self._grant("vision", project_dir, grant)
        paid_allowed = bool(allow_paid) or self._fake("vision", project_dir)
        role_allow = allow or (lambda e: (self.pricing.is_free(e.get("card")) or paid_allowed, "paid or unknown vision model; enable Allow paid models"))
        approved_price = grant.price if grant else None
        price_of = (lambda e: self.pricing.text_cost(e.get("card"), None)) if grant else None
        approved_unknown_entry = None
        if grant and paid_allowed:
            # Redemption validates the consumed proposal; chain position is not approval.
            prop = approvals.get(project_dir, grant.proposal_id)
            approved_unknown_entry = ((prop.get("summary") or {}).get("provider"), prop["model"])
        r = self.run("vision", lambda a, m: a.vision(m, prompt, images, opts), project_dir, role_allow, approved_price, price_of,
                     approved_unknown_entry=approved_unknown_entry)
        out = r["result"]
        cost, src = self._cost("vision", out, r["card"])
        return {**out, "cost": cost, "cost_source": src, "provider": r["provider"], "attempts": r["attempts"]}

    def image(self, prompt, refs=(), aspect_ratio="9:16", opts=None, project_dir=None, *, grant=None, first=None, required=None):
        grant = self._grant("image", project_dir, grant, first)
        approved_price = grant.price if grant else None
        price_of = lambda e: self.pricing.image_price(e["card"], len(refs))
        r = self.run("image", lambda a, m: a.image(m, prompt, refs, aspect_ratio, opts), project_dir, None, approved_price, price_of, first=first, required=required)
        out = r["result"]
        cost, src = self._cost("image", out, r["card"], extra={"refs": len(refs), "quoted": grant.price if grant else None})
        return {**out, "cost": cost, "cost_source": src, "provider": r["provider"], "attempts": r["attempts"]}

    def image_edit(self, image_path, prompt, edit_mode="inpaint_insertion", mask_mode="MASK_MODE_BACKGROUND", aspect_ratio="9:16", opts=None, project_dir=None, *, grant=None):
        grant = self._grant("image", project_dir, grant)
        approved_price = grant.price if grant else None
        price_of = lambda e: self.pricing.image_price(e["card"])
        r = self.run("image", lambda a, m: a.image_edit(m, image_path, prompt, edit_mode=edit_mode, mask_mode=mask_mode, opts={**(opts or {}), "aspect_ratio": aspect_ratio}), project_dir, None, approved_price, price_of)
        out = r["result"]
        cost, src = self._cost("image", out, r["card"], extra={"quoted": grant.price if grant else None})
        return {**out, "cost": cost, "cost_source": src, "provider": r["provider"], "attempts": r["attempts"]}

    def video_price(self, entry, req, refs=0):
        return self.pricing.video_price(entry["card"], req["seconds"], req.get("resolution", "720p"), req.get("audio", False), refs)

    def video_extend(self, video_path, prompt, seconds=5, aspect_ratio="16:9", resolution="720p", project_dir=None, *, grant=None, timeout=None, first=None):
        grant = self._grant("video", project_dir, grant, first)
        approved_price = grant.price if grant else None
        req = {"seconds": seconds, "resolution": resolution, "audio": False}
        price_of = lambda e: self.video_price(e, req)
        pol = self.policy("video", project_dir) if not self._fake("video", project_dir) else cfg.default_policy("video")
        limit = timeout if timeout is not None else pol.get("timeout", 1500)
        state = {}

        def call(adapter, model):
            job = adapter.video_extend(model, video_path, prompt, seconds=seconds, aspect_ratio=aspect_ratio, resolution=resolution)
            state["job"] = {**job, "provider": adapter.conn["id"]}
            t0 = self.clock()
            while True:
                try:
                    st = adapter.video_poll(job)
                except Retryable:
                    st = {"status": "pending", "error": None, "cost": None}
                if st["status"] == "done":
                    try:
                        data = adapter.video_download(job)
                    except Retryable:
                        # The provider job already exists; never retry the whole
                        # callback and submit a second paid job. Reconcile later.
                        return {"status": "pending", "job": state["job"]}
                    except ProviderError as ex:
                        raise _Stop(f"video download failed: {scrub(ex, adapter.secret)[:200]}")
                    return {"status": "done", "bytes": data, "reported": st.get("cost"), "job": state["job"]}
                if st["status"] == "failed":
                    raise _Stop(st.get("error") or "extension failed")
                if self.clock() - t0 > limit:
                    return {"status": "pending", "job": state["job"]}
                self.sleep(self.poll_seconds)

        try:
            r = self.run("video", call, project_dir, None, approved_price, price_of, first=first)
        except _Stop as ex:
            job = state.get("job") or {}
            return {"status": "failed", "error": ex.args[0], "job": job, "cost": 0.0, "cost_source": "unknown", "provider": job.get("provider", ""),
                    "model": job.get("model", ""), "attempts": ex.attempts}
        out = r["result"]
        base = {"provider": r["provider"], "model": r["model"], "attempts": r["attempts"], "job": out["job"]}
        if out["status"] == "pending":
            return {**base, "status": "pending", "cost": 0.0, "cost_source": "unknown"}
        cost, src = self._cost("video", {"cost": out.get("reported")}, r["card"], extra={**req, "quoted": grant.price if grant else None})
        return {**base, "status": "done", "bytes": out["bytes"], "cost": cost, "cost_source": src}

    def video_task(self, task, video_path, prompt, params, reference=None, seconds=5, resolution="720p", project_dir=None, *, grant=None, timeout=None, first=None):
        """A paid clip tool (upscale, reframe, video_to_video, motion_transfer) on one source clip. Same grant, price-bound and never-resubmit rules as video_extend.
        Only a model whose profile lists the task AND whose adapter implements it is tried; nothing falls back to a different task."""
        if self.catalog is None:
            raise ChainError("no model catalog is loaded, so no model can be shown to support this task", code="unconfigured")
        grant = self._grant("video", project_dir, grant, first)
        approved_price = grant.price if grant else None
        price_of = lambda e: self.pricing.task_price(e["card"], seconds, resolution, refs=int(reference is not None))
        pol = self.policy("video", project_dir) if not self._fake("video", project_dir) else cfg.default_policy("video")
        limit = timeout if timeout is not None else pol.get("timeout", 1500)
        state = {}

        def call(adapter, model):
            job = adapter.video_task(model, task, video_path, prompt, params, reference=reference, seconds=seconds)
            state["job"] = {**job, "provider": adapter.conn["id"]}
            t0 = self.clock()
            while True:
                try:
                    st = adapter.video_poll(job)
                except Retryable:
                    st = {"status": "pending", "error": None, "cost": None}
                if st["status"] == "done":
                    try:
                        data = adapter.video_download(job)
                    except Retryable:
                        return {"status": "pending", "job": state["job"]}      # the job exists: never submit a second paid one
                    except ProviderError as ex:
                        raise _Stop(f"video download failed: {scrub(ex, adapter.secret)[:200]}")
                    return {"status": "done", "bytes": data, "reported": st.get("cost"), "job": state["job"]}
                if st["status"] == "failed":
                    raise _Stop(st.get("error") or f"{task} failed")
                if self.clock() - t0 > limit:
                    return {"status": "pending", "job": state["job"]}
                self.sleep(self.poll_seconds)

        try:
            r = self.run("video", call, project_dir, None, approved_price, price_of, first=first, required={"task": task})
        except _Stop as ex:
            job = state.get("job") or {}
            return {"status": "failed", "error": ex.args[0], "job": job, "cost": 0.0, "cost_source": "unknown", "provider": job.get("provider", ""),
                    "model": job.get("model", ""), "attempts": ex.attempts}
        out = r["result"]
        base = {"provider": r["provider"], "model": r["model"], "attempts": r["attempts"], "job": out["job"]}
        if out["status"] == "pending":
            return {**base, "status": "pending", "cost": 0.0, "cost_source": "unknown"}
        reported = out.get("reported")
        computed = self.pricing.task_price(r["card"], seconds, resolution, refs=int(reference is not None))
        cost, src = self.pricing.actual_cost(reported, computed)
        if reported is None and computed is None and r["card"] and not self.pricing.is_free(r["card"]) and grant:
            cost, src = grant.price, "estimated"
        return {**base, "status": "done", "bytes": out["bytes"], "cost": cost, "cost_source": src}

    def audio_task(self, task, *, project_dir=None, grant=None, text="", prompt="", voice_id="", source_path="", video_path="", audio_path="", seconds=0, language="", options=None, chars=0):
        """Run one catalog-declared audio task. Paid roles always redeem a human-issued Grant."""
        if task not in ("tts", "music", "sfx", "lipsync", "transcribe"):
            raise ChainError(f"unsupported audio task: {task}")
        if self.catalog is None:
            raise ChainError("no model catalog is loaded, so no model can be shown to support this task", code="unconfigured")
        grant = self._grant(task, project_dir, grant)
        seconds = int(seconds or 0)
        options = dict(options or {})
        price_of = lambda e: self.pricing.audio_task_price(e["card"], task, chars=chars, seconds=seconds)
        approved_price = grant.price if grant else None
        state = {}

        def call(adapter, model):
            if task == "tts":
                return adapter.tts(model, text, voice_id, {**options, "language_code": language})
            if task == "music":
                return adapter.music(model, prompt, seconds, options)
            if task == "sfx":
                return adapter.sfx(model, prompt, seconds, options)
            if task == "transcribe":
                return adapter.transcribe(model, source_path or audio_path, {**options, "language_code": language})
            if hasattr(adapter, "lipsync_submit"):
                job = adapter.lipsync_submit(model, video_path, audio_path, options)
            else:
                return adapter.lipsync(model, video_path, audio_path, options)
            state["job"] = {**job, "provider": adapter.conn["id"]}
            while True:
                result = adapter.lipsync_poll(job)
                if result["status"] == "failed":
                    raise _Stop(result.get("error") or "lip sync failed")
                if result["status"] == "done":
                    return {"bytes": adapter.lipsync_download(job), "cost": result.get("cost"), "job": job, "mime": "video/mp4"}
                if self.clock() - state.setdefault("started", self.clock()) > options.get("timeout", 1500):
                    return {"pending": True, "job": job}
                self.sleep(self.poll_seconds)

        r = self.run(task, call, project_dir, approved_price=approved_price, price_of=price_of, required={"task": task})
        out = r["result"]
        if out.get("pending"):
            return {"status": "pending", "job": out.get("job"), "provider": r["provider"], "model": r["model"]}
        computed = price_of({"card": r["card"]})
        cost, source = self.pricing.actual_cost(out.get("cost"), computed)
        if out.get("cost") is None and computed is None and grant and not self.pricing.is_free(r["card"]):
            cost, source = grant.price, "estimated"      # a paid call that reports no cost and cannot be recomputed is logged at the approved quote, never $0
        if task == "transcribe":
            return {"status": "done", "transcript": out, "provider": r["provider"], "model": r["model"], "cost": cost, "cost_source": source}
        return {"status": "done", "bytes": out.get("bytes", b""), "mime": out.get("mime", "application/octet-stream"),
                "provider": r["provider"], "model": r["model"], "cost": cost, "cost_source": source}

    def video(self, req, project_dir=None, *, grant=None, timeout=None, first=None, required=None, ref_count=0):
        """-> {"status":"done","bytes",...} | {"status":"pending","job"} | {"status":"failed","error",...}. Raises ChainError/NeedsNewApproval."""
        grant = self._grant("video", project_dir, grant, first)
        approved_price = grant.price if grant else None
        price_of = lambda e: self.video_price(e, req, ref_count)
        pol = self.policy("video", project_dir) if not self._fake("video", project_dir) else cfg.default_policy("video")
        limit = timeout if timeout is not None else pol.get("timeout", 1500)
        state = {}

        def call(adapter, model):
            job = adapter.video_submit(model, req)
            state["job"] = {**job, "provider": adapter.conn["id"]}
            t0 = self.clock()
            while True:
                try:
                    st = adapter.video_poll(job)
                except Retryable:
                    st = {"status": "pending", "error": None, "cost": None}
                if st["status"] == "done":
                    try:
                        data = adapter.video_download(job)
                    except Retryable:
                        # The provider job already exists; never retry the whole
                        # callback and submit a second paid job. Reconcile later.
                        return {"status": "pending", "job": state["job"]}
                    except ProviderError as ex:
                        raise _Stop(f"video download failed: {scrub(ex, adapter.secret)[:200]}")
                    return {"status": "done", "bytes": data, "reported": st.get("cost"), "job": state["job"]}
                if st["status"] == "failed":
                    raise _Stop(st.get("error") or "generation failed")
                if self.clock() - t0 > limit:
                    return {"status": "pending", "job": state["job"]}
                self.sleep(self.poll_seconds)

        try:
            r = self.run("video", call, project_dir, None, approved_price, price_of, first=first, required=required)
        except _Stop as ex:
            job = state.get("job") or {}
            return {"status": "failed", "error": ex.args[0], "job": job, "cost": 0.0, "cost_source": "unknown", "provider": job.get("provider", ""),
                    "model": job.get("model", ""), "attempts": ex.attempts}
        out = r["result"]
        base = {"provider": r["provider"], "model": r["model"], "attempts": r["attempts"], "job": out["job"]}
        if out["status"] == "pending":
            return {**base, "status": "pending", "cost": 0.0, "cost_source": "unknown"}
        cost, src = self._cost("video", {"cost": out.get("reported")}, r["card"], extra={**req, "refs": ref_count, "quoted": grant.price if grant else None})
        return {**base, "status": "done", "bytes": out["bytes"], "cost": cost, "cost_source": src}

    def review(self, prompt, images, opts=None, project_dir=None, *, grant=None, allow_paid=False):
        """Compatibility alias for the grant-protected paid vision call."""
        return self.vision(prompt, images, opts, project_dir=project_dir, grant=grant, allow_paid=allow_paid)

    def fetch_video(self, job, req=None):
        """Resolve a job left pending by a timeout. job = {"job_id","model","provider"}."""
        p = self.providers().get(job.get("provider")) or ({"id": "fake", "type": "fake"} if job.get("provider") == "fake" else None)
        if p is None:
            raise ChainError("The provider of this job was removed from Settings.", code="unconfigured")
        adapter = self.adapter(p)
        st = adapter.video_poll(job)
        if st["status"] == "pending":
            return {"status": "pending", "job": job}
        if st["status"] == "failed":
            reported = st.get("cost")
            return {"status": "failed", "error": st.get("error") or "failed", "cost": None if reported is None else float(reported),
                    "cost_source": "reported" if reported is not None else "unreconciled", "job": job}
        card = self.pricing.card(p["id"], p["type"], job["model"])
        cost, src = self.pricing.actual_cost(st.get("cost"), self.pricing.video_price(card, (req or {}).get("seconds", 0), (req or {}).get("resolution", "720p"), (req or {}).get("audio", False)) if req else None)
        return {"status": "done", "bytes": adapter.video_download(job), "cost": cost, "cost_source": src, "job": job}


class _Stop(ProviderError):
    """Internal: a video job was accepted and then failed."""
    def __init__(self, msg):
        super().__init__(msg)
        self.attempts = []
