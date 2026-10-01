"""Role chains: run one purpose (chat, vision, image, video ...) through its ordered list of models, with fallback.  Standard library only.

RoleRunner.run(role, call, ...) tries each model of the role's chain in order and returns on the first success.
Outcome handling for one model:
  Retryable (429, 5xx, timeout, empty answer) -> retry up to policy["retries"] times with backoff, then try the next model.
  AuthError                                   -> the provider is marked UNHEALTHY for a while (skipped later), try the next model.
  Rejected / NotFound / Unsupported           -> try the next model.
All attempts are kept; if every model fails ONE ChainError lists them all.
Cost rule: when `approved_price` is given (an image/video action a human approved at an exact price), a model whose price is unknown or higher
is never used silently; if nothing cheaper works the runner raises NeedsNewApproval so a human sees the new price.
Video: submit -> poll -> download.  A job that was ACCEPTED and then fails is NOT retried on another model (money may be spent); a timeout
returns {"status":"pending", "job": ...} so `sync` can finish it later.
"""
import time

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
        self.fake_for = fake_for        # optional (role, project_dir) -> bool: lets one project run some roles on the fake provider

    def _fake(self, role, project_dir=None):
        return self.fake_for(role, project_dir) if self.fake_for else self.fake_mode()

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
        if not self.trust_transport and not self.secrets.has(p.get("secret_ref") or p["id"]) and not (p["type"] == "custom" and p.get("base_url")):
            return "no API key"
        return None

    def resolve(self, role, project_dir=None, configured=False):
        """Entries for the chain: {"provider","ptype","model","problem","card","index"}; problem is None when the entry can be called."""
        if not configured and self._fake(role, project_dir):      # test mode runs everything on the built-in test provider; `configured` shows the real chain anyway
            fp = {"id": "fake", "type": "fake", "label": "Built-in test", "enabled": True}
            model = "fake/" + {"chat": "llm", "verify": "llm", "vision": "vision", "image": "image", "video": "video"}[role]
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

    def policy(self, role, project_dir=None):
        return cfg.effective_roles(self.dir, project_dir)["roles"][role]["policy"]

    # -------------------------------------------------------------- the generic runner
    def run(self, role, call, project_dir=None, allow=None, approved_price=None, price_of=None, retry_after_submit=False):
        """call(adapter, model) -> result.  Returns {"result", "provider", "model", "card", "attempts"}."""
        entries = self.resolve(role, project_dir)
        if not entries:
            raise ChainError(f"No model is set for '{role}'. Add a provider and pick a model in Settings.", code="unconfigured")
        pol = self.policy(role, project_dir) if not self._fake(role, project_dir) else cfg.default_policy(role)
        attempts, too_dear = [], None
        sick = [e for e in entries if e["problem"] is None and self.health.unhealthy(e["provider"]["id"])]
        for e in entries:
            who = f"{e['provider'].get('label') or e['provider']['id']}:{e['model']}"
            if e["problem"]:
                attempts.append({"who": who, "error": e["problem"], "skipped": True})
                continue
            if allow:
                ok, why = allow(e)
                if not ok:
                    attempts.append({"who": who, "error": why, "skipped": True})
                    continue
            if approved_price is not None:
                price = price_of(e) if price_of else None
                if price is None:
                    attempts.append({"who": who, "error": "price unknown (set a price in Settings)", "skipped": True})
                    continue
                if price > approved_price + 1e-9:
                    attempts.append({"who": who, "error": f"costs ${price:.3f} (more than the approved ${approved_price:.3f})", "skipped": True})
                    too_dear = too_dear or (e, price)
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
        if too_dear:
            e, price = too_dear
            raise NeedsNewApproval(f"Every usable '{role}' model costs more than the approved price. Next choice: {e['model']} at ${price:.3f}.", e, price, attempts)
        raise ChainError(f"All '{role}' models failed: " + " | ".join(f"{a['who']} -> {a['error']}" for a in attempts), attempts)

    # -------------------------------------------------------------- conveniences
    def _cost(self, role, out, card, usage=None, extra=None):
        reported = out.get("cost")
        computed = None
        if role in ("chat", "verify", "vision"):
            computed = self.pricing.text_cost(card, usage or out.get("usage"))
        elif role == "image":
            computed = self.pricing.image_price(card)
        elif role == "video" and extra:
            computed = self.pricing.video_price(card, extra["seconds"], extra.get("resolution", "720p"), extra.get("audio", False))
        return self.pricing.actual_cost(reported, computed)

    def chat(self, role, messages, opts=None, project_dir=None, allow=None):
        r = self.run(role, lambda a, m: a.chat(m, messages, opts), project_dir, allow)
        out = r["result"]
        cost, src = self._cost(role, out, r["card"])
        return {**out, "cost": cost, "cost_source": src, "provider": r["provider"], "attempts": r["attempts"]}

    def vision(self, prompt, images, opts=None, project_dir=None, allow=None):
        r = self.run("vision", lambda a, m: a.vision(m, prompt, images, opts), project_dir, allow)
        out = r["result"]
        cost, src = self._cost("vision", out, r["card"])
        return {**out, "cost": cost, "cost_source": src, "provider": r["provider"], "attempts": r["attempts"]}

    def image(self, prompt, refs=(), aspect_ratio="9:16", opts=None, project_dir=None, approved_price=None):
        price_of = lambda e: self.pricing.image_price(e["card"])
        r = self.run("image", lambda a, m: a.image(m, prompt, refs, aspect_ratio, opts), project_dir, None, approved_price, price_of)
        out = r["result"]
        cost, src = self._cost("image", out, r["card"])
        return {**out, "cost": cost, "cost_source": src, "provider": r["provider"], "attempts": r["attempts"]}

    def video_price(self, entry, req):
        return self.pricing.video_price(entry["card"], req["seconds"], req.get("resolution", "720p"), req.get("audio", False))

    def video(self, req, project_dir=None, approved_price=None, timeout=None):
        """-> {"status":"done","bytes",...} | {"status":"pending","job"} | {"status":"failed","error",...}. Raises ChainError/NeedsNewApproval."""
        price_of = lambda e: self.video_price(e, req)
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
                    return {"status": "done", "bytes": adapter.video_download(job), "reported": st.get("cost"), "job": state["job"]}
                if st["status"] == "failed":
                    raise _Stop(st.get("error") or "generation failed")
                if self.clock() - t0 > limit:
                    return {"status": "pending", "job": state["job"]}
                self.sleep(self.poll_seconds)

        try:
            r = self.run("video", call, project_dir, None, approved_price, price_of)
        except _Stop as ex:
            job = state.get("job") or {}
            return {"status": "failed", "error": ex.args[0], "job": job, "cost": 0.0, "cost_source": "unknown", "provider": job.get("provider", ""),
                    "model": job.get("model", ""), "attempts": ex.attempts}
        out = r["result"]
        base = {"provider": r["provider"], "model": r["model"], "attempts": r["attempts"], "job": out["job"]}
        if out["status"] == "pending":
            return {**base, "status": "pending", "cost": 0.0, "cost_source": "unknown"}
        cost, src = self._cost("video", {"cost": out.get("reported")}, r["card"], extra=req)
        return {**base, "status": "done", "bytes": out["bytes"], "cost": cost, "cost_source": src}

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
            return {"status": "failed", "error": st.get("error") or "failed", "cost": float(st.get("cost") or 0), "job": job}
        card = self.pricing.card(p["id"], p["type"], job["model"])
        cost, src = self.pricing.actual_cost(st.get("cost"), self.pricing.video_price(card, (req or {}).get("seconds", 0), (req or {}).get("resolution", "720p"), (req or {}).get("audio", False)) if req else None)
        return {"status": "done", "bytes": adapter.video_download(job), "cost": cost, "cost_source": src, "job": job}


class _Stop(ProviderError):
    """Internal: a video job was accepted and then failed."""
    def __init__(self, msg):
        super().__init__(msg)
        self.attempts = []
