"""Settings operations for providers, models, prices and role chains (mixed into Workspace).  Standard library only.

Everything here returns plain JSON-able dicts for the web API, and NEVER returns a secret (only whether it is set and its last 4 characters).
"""
import re
import time

from aistudio import costlog, migrate as migrate_mod, pricing as pricing_mod
from aistudio.providers import base as pbase, config as pconf

MODELS_TTL = 600


def _err(msg):
    from aistudio.service import ServiceError
    return ServiceError(msg)


def _slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:30]
    return s or "provider"


def price_summary(card):
    if not card:
        return None
    k = card.get("kind")
    if k == "text":
        if card.get("free"):
            return "free"
        if "per_call" in card:
            return f"${card['per_call']:.3f}/call"
        return f"${card['input_per_1m']:g} / ${card['output_per_1m']:g} per 1M tokens"
    if k == "image":
        return f"${card['per_image']:.3f}/image"
    if k == "video":
        rates = []
        for d in card["per_second"].values():
            if isinstance(d, (int, float)):
                rates.append(d)
            elif isinstance(d, dict):
                rates += [v for v in d.values() if isinstance(v, (int, float))]
            elif isinstance(d, list):
                rates += [t["rate"] for t in d if "rate" in t]
        return (f"${min(rates):g}/s" if min(rates) == max(rates) else f"${min(rates):g}-{max(rates):g}/s") if rates else None
    return None


class SettingsMixin:
    # ---------------------------------------------------------------- providers
    def _providers_doc(self):
        self.ensure_settings()
        return pconf.load_providers(self.settings_dir)

    def _provider(self, pid):
        p = next((x for x in self._providers_doc() if x["id"] == pid), None)
        if p is None:
            raise _err(f"no such provider: {pid}")
        return p

    def _secret_ref(self, p):
        return p.get("secret_ref") or p["id"]

    def _used_in(self, pid, project=None):
        doc = pconf.effective_roles(self.settings_dir, project)
        return [r for r in pconf.ROLES if any(c["provider"] == pid for c in doc["roles"][r]["chain"])]

    def _status(self, p):
        if not p.get("enabled", True):
            return {"state": "inactive", "message": "Disabled"}
        if p["type"] != "fake" and not self.secrets.has(self._secret_ref(p)) and not (p["type"] == "custom" and p.get("base_url")):
            return {"state": "needs_key", "message": "Add an API key"}
        bad = self._health.unhealthy(p["id"])
        if bad:
            return {"state": "error", "message": bad}
        t = self._health.tests.get(p["id"])
        if t and not t["ok"]:
            return {"state": "error", "message": t["message"], "checked_at": t["checked_at"]}
        if t:
            return {"state": "active", "message": t["message"], "checked_at": t["checked_at"]}
        return {"state": "active", "message": "Not tested yet"}

    def _provider_view(self, p):
        meta = pconf.PROVIDER_TYPES[p["type"]]
        ref = self._secret_ref(p)
        return {"id": p["id"], "type": p["type"], "label": p["label"], "sub": meta["sub"], "base_url": p.get("base_url", ""), "enabled": p.get("enabled", True),
                "fields": meta["fields"], "capabilities": pconf.capabilities_of(p["type"]), "secret": self.secrets.masked(ref) if p["type"] != "fake" else {"set": True, "fields": {}},
                "secret_source": "stored", "status": self._status(p), "used_in": self._used_in(p["id"])}

    def provider_types(self):
        return pconf.provider_types()

    def setup_status(self):
        """First-run gate: the app needs at least one real provider that can be called and a usable chat model before anything else.
        Image and video models are reported too (needed before generating) but do not block.  Not enforced when AISTUDIO_ALL_TEST=1 is set
        (tests, CI and demos that run on the built-in test provider)."""
        self.ensure_settings()
        runner = self.runner()
        real = [p for p in self._providers_doc() if p["type"] != "fake"]
        ready = [p["id"] for p in real if runner._usable(p) is None]
        roles = {}
        for role in ("chat", "image", "video"):
            ents = runner.resolve(role, None, configured=True)
            good = [e for e in ents if e["problem"] is None and e["ptype"] != "fake"]
            roles[role] = {"title": pconf.ROLE_INFO[role]["title"], "ready": bool(good), "models": [e["model"] for e in good][:3],
                           "problems": [f"{e['model']}: {e['problem']}" for e in ents if e["problem"] and e["ptype"] != "fake"][:3], "required": role == "chat"}
        needed = not self.forced_test() and not (ready and roles["chat"]["ready"])
        return {"needed": needed, "locked": self.forced_test(), "providers": {"ready": ready, "total": len(real)}, "roles": roles}

    def providers_list(self):
        return {"providers": [self._provider_view(p) for p in self._providers_doc()], "secrets_backend": self.secrets.backend()}

    def _save_providers(self, provs):
        try:
            pconf.save_providers(self.settings_dir, provs)
        except ValueError as e:
            raise _err(str(e)) from None

    def provider_create(self, d):
        provs = self._providers_doc()
        ptype = d.get("type")
        if ptype not in pconf.PROVIDER_TYPES or ptype == "fake":
            raise _err("choose one of the listed provider types")
        label = str(d.get("label") or pconf.PROVIDER_TYPES[ptype]["label"]).strip()
        base, pid, n = _slug(d.get("id") or label), None, 1
        ids = {p["id"] for p in provs}
        pid = base
        while pid in ids:
            n += 1
            pid = f"{base}-{n}"
        p = {"id": pid, "type": ptype, "label": label, "base_url": str(d.get("base_url") or "").strip(), "enabled": True}
        self._save_providers(provs + [p])
        if d.get("secret"):
            self.provider_secret_put(pid, d["secret"], _check=pconf.PROVIDER_TYPES[ptype]["fields"])
        return self._provider_view(p)

    def provider_update(self, pid, d):
        provs = self._providers_doc()
        p = next((x for x in provs if x["id"] == pid), None)
        if p is None:
            raise _err(f"no such provider: {pid}")
        if p["type"] == "fake" and "enabled" in d and not d["enabled"]:
            raise _err("the built-in test provider cannot be disabled")
        for k in ("label", "base_url"):
            if k in d:
                p[k] = str(d[k] or "").strip()
        if "enabled" in d:
            p["enabled"] = bool(d["enabled"])
        self._save_providers(provs)
        self._health.clear(pid)
        return self._provider_view(p)

    def provider_secret_put(self, pid, fields, _check=None):
        p = self._provider(pid)
        need = _check if _check is not None else pconf.PROVIDER_TYPES[p["type"]]["fields"]
        if not isinstance(fields, dict) or any(not str(fields.get(f) or "").strip() for f in need):
            raise _err("fill in: " + ", ".join(need))
        ref = f"{p['id']}"
        try:
            self.secrets.set(ref, {f: str(fields[f]) for f in need})
        except Exception as e:
            raise _err(str(e)) from None
        if p.get("secret_ref"):                                    # an old explicit reference: the stored key replaces it
            provs = self._providers_doc()
            for x in provs:
                if x["id"] == pid:
                    x.pop("secret_ref", None)
            self._save_providers(provs)
        self._health.clear(pid)
        return self._provider_view(self._provider(pid))

    def provider_secret_delete(self, pid):
        p = self._provider(pid)
        self.secrets.delete(self._secret_ref(p))
        return self._provider_view(p)

    def provider_delete(self, pid, force=False):
        p = self._provider(pid)
        if p["type"] == "fake":
            raise _err("the built-in test provider cannot be removed")
        used = self._used_in(pid)
        if used and not force:
            raise _err(f"{p['label']} is used by: {', '.join(used)}. Remove it from those chains first, or delete anyway.")
        provs = [x for x in self._providers_doc() if x["id"] != pid]
        doc = pconf.load_roles(self.settings_dir)
        for r in doc["roles"].values():
            r["chain"] = [c for c in r["chain"] if c["provider"] != pid]
        self._save_providers(provs)
        pconf.save_roles(self.settings_dir, doc, provs)
        self.secrets.delete(self._secret_ref(p))
        return {"ok": True, "removed_from": used}

    def provider_test(self, pid):
        p = self._provider(pid)
        try:
            adapter = pconf.build_adapter(p, self.secrets, self._adapter_transport())
            res = adapter.test()
        except pbase.ProviderError as e:
            res = {"ok": False, "message": self.secrets.redact(e)[:200]}
        res = {**res, "message": self.secrets.redact(res.get("message", ""))}
        self._health.record_test(pid, res)
        return {"result": res, "provider": self._provider_view(p)}

    def _adapter_transport(self):
        return self.runner().transport

    # ---------------------------------------------------------------- models and prices
    def _models_file(self):
        return self.settings_dir / "models.json"

    def _models_doc(self):
        import json
        try:
            return json.loads(self._models_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_models_doc(self, doc):
        import json
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._models_file().with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        tmp.replace(self._models_file())

    def _discover(self, p, refresh=False):
        cache = getattr(self, "_model_cache", None)
        if cache is None:
            cache = self._model_cache = {}
        hit = cache.get(p["id"])
        if hit and not refresh and time.time() - hit[0] < MODELS_TTL:
            return hit[1], None
        try:
            models = pconf.build_adapter(p, self.secrets, self._adapter_transport()).list_models()
            cache[p["id"]] = (time.time(), models)
            return models, None
        except pbase.ProviderError as e:
            return (hit[1] if hit else []), self.secrets.redact(e)[:200]

    def _model_view(self, p, m, pr):
        card = pr.card(p["id"], p["type"], m["id"])
        return {"provider": p["id"], "provider_label": p["label"], "ptype": p["type"], "id": m["id"], "name": m.get("name") or m["id"], "capability": m["capability"],
                "price": price_summary(card), "priced": card is not None, "free": pr.is_free(card), "card": card, "suggest": None if card else pr.suggest(m["id"]),
                "custom": bool(m.get("custom"))}

    def provider_models(self, pid, refresh=False):
        p = self._provider(pid)
        pr = self.pricing()
        models, error = self._discover(p, refresh)
        custom = [{**m, "custom": True} for m in (self._models_doc().get("models") or []) if m.get("provider") == pid]
        seen = {m["id"] for m in models}
        allm = list(models) + [m for m in custom if m["id"] not in seen]
        return {"models": [self._model_view(p, m, pr) for m in allm], "error": error}

    def models_all(self, capability=None):
        out, errors = [], {}
        for p in self._providers_doc():
            if not p.get("enabled", True) or self._status(p)["state"] == "needs_key":
                continue
            r = self.provider_models(p["id"])
            if r["error"]:
                errors[p["id"]] = r["error"]
            out += [m for m in r["models"] if capability is None or m["capability"] == capability or (capability == "vision" and m["capability"] == "chat")]
        return {"models": out, "errors": errors}

    def model_add(self, pid, model_id, capability):
        self._provider(pid)
        if capability not in ("chat", "vision", "image", "video") or not pconf.MODEL_RE.match(str(model_id or "")):
            raise _err("give a model id and a capability (chat, vision, image or video)")
        doc = self._models_doc()
        models = [m for m in doc.get("models", []) if not (m["provider"] == pid and m["id"] == model_id)]
        models.append({"provider": pid, "id": model_id, "name": model_id, "capability": capability})
        self._save_models_doc({**doc, "models": models})
        return self.provider_models(pid)

    def price_put(self, pid, model, card):
        self._provider(pid)
        errs = pricing_mod.validate_card(card)
        if errs:
            raise _err("; ".join(errs))
        doc = self._models_doc()
        doc.setdefault("prices", {})[pricing_mod.key(pid, model)] = card
        self._save_models_doc(doc)
        return {"price": price_summary(card), "card": card}

    def price_delete(self, pid, model):
        doc = self._models_doc()
        doc.get("prices", {}).pop(pricing_mod.key(pid, model), None)
        self._save_models_doc(doc)
        return {"ok": True}

    # ---------------------------------------------------------------- roles
    def _chain_view(self, role, project=None):
        runner = self.runner()
        entries = runner.resolve(role, project, configured=True)
        pr = self.pricing()
        prim_price = None
        out = []
        for e in entries:
            card = e["card"]
            price = None
            if role == "video" and card:
                price = pr.video_price(card, 4, "720p", False)
            elif role == "image" and card:
                price = pr.image_price(card)
            if prim_price is None and e["problem"] is None:
                prim_price = price
            out.append({"provider": e["provider"]["id"], "provider_label": e["provider"].get("label") or e["provider"]["id"], "ptype": e["ptype"], "model": e["model"],
                        "problem": e["problem"], "price": price_summary(card), "priced": card is not None, "free": pr.is_free(card),
                        "unhealthy": self._health.unhealthy(e["provider"]["id"]),
                        "dearer": bool(role in ("video", "image") and price is not None and prim_price is not None and price > prim_price + 1e-9)})
        return out

    def roles_get(self, project=None):
        p = self.pdir(project) if project else None
        self.ensure_settings()
        doc = pconf.effective_roles(self.settings_dir, p)
        base = pconf.load_roles(self.settings_dir)
        override = {}
        if p:
            override = (self._read(p, "roles.override.json", {}) or {}).get("roles", {})
        roles = {}
        for r in pconf.ROLES:
            info = pconf.ROLE_INFO[r]
            roles[r] = {"title": info["title"], "sub": info["sub"], "capability": pconf.ROLE_CAPABILITY[r], "chain": self._chain_view(r, p),
                        "policy": doc["roles"][r]["policy"], "overridden": r in override}
        return {"roles": roles, "allow_paid": base["allow_paid"], "ai_cap_usd": base["ai_cap_usd"], "auto_verify": base["auto_verify"]}

    def roles_put(self, role, chain, policy=None, project=None):
        self.ensure_settings()
        provs = self._providers_doc()
        refs = [{"provider": str(c.get("provider")), "model": str(c.get("model"))} for c in (chain or [])]
        errs = pconf.validate_chain(role, refs, provs)
        if errs:
            raise _err("; ".join(errs))
        if project:
            import json
            p = self.pdir(project)
            ov = self._read(p, "roles.override.json", {"roles": {}}) or {"roles": {}}
            if refs:
                ov["roles"][role] = {"chain": refs, **({"policy": policy} if policy else {})}
            else:
                ov["roles"].pop(role, None)            # empty = back to the workspace chain
            (p / "roles.override.json").write_text(json.dumps(ov, indent=2), encoding="utf-8")
        else:
            doc = pconf.load_roles(self.settings_dir)
            doc["roles"][role] = {"chain": refs, "policy": {**doc["roles"][role]["policy"], **(policy or {})}}
            try:
                pconf.save_roles(self.settings_dir, doc, provs)
            except ValueError as e:
                raise _err(str(e)) from None
        return self.roles_get(project)

    def limits_put(self, d):
        self.ensure_settings()
        doc = pconf.load_roles(self.settings_dir)
        for k in ("allow_paid", "ai_cap_usd", "auto_verify"):
            if k in d:
                doc[k] = d[k]
        try:
            pconf.save_roles(self.settings_dir, doc, self._providers_doc())
        except ValueError as e:
            raise _err(str(e)) from None
        return self.roles_get()

    def roles_reset(self):
        self.ensure_settings()
        provs = self._providers_doc()
        _, fresh, _ = migrate_mod.plan(self.root, force_openrouter=any(p["type"] == "openrouter" for p in provs))
        ids = {p["id"] for p in provs}
        old = pconf.load_roles(self.settings_dir)
        for r in pconf.ROLES:
            fresh["roles"][r]["chain"] = [c for c in fresh["roles"][r]["chain"] if c["provider"] in ids]
        fresh.update({k: old[k] for k in ("allow_paid", "ai_cap_usd", "auto_verify")})
        pconf.save_roles(self.settings_dir, fresh, provs)
        return self.roles_get()

    def roles_test(self, role, project=None):
        """Free check of every model in a chain: provider usable, model known to the provider. Chat roles also get a 1-token ping when the model is free."""
        p = self.pdir(project) if project else None
        runner, out = self.runner(), []
        for e in runner.resolve(role, p, configured=True):
            row = {"provider": e["provider"]["id"], "model": e["model"], "ok": False, "message": ""}
            if e["problem"]:
                row["message"] = e["problem"]
            else:
                known = self.provider_models(e["provider"]["id"])
                ids = {m["id"] for m in known["models"]}
                cap = pconf.ROLE_CAPABILITY[role]
                comparable = any(m["capability"] == cap or (cap == "vision" and m["capability"] == "chat") for m in known["models"])
                if ids and not comparable:
                    # the provider's list has no models of this kind (OpenRouter lists text models only), so the id cannot be checked for free
                    row.update(ok=True, message=f"key ready; this provider does not list {cap} models, so the id could not be verified without generating")
                    out.append(row)
                    continue
                if ids and e["model"] not in ids:
                    row["message"] = "the provider does not list this model"
                elif known["error"] and not ids:
                    row["message"] = known["error"]
                else:
                    row.update(ok=True, message="ready")
                    if role in ("chat", "verify") and e["card"] and e["card"].get("free"):
                        try:
                            runner.adapter(e["provider"]).chat(e["model"], [{"role": "user", "content": "Reply with OK"}], {"max_tokens": 5})
                            row["message"] = "answered"
                        except pbase.ProviderError as ex:
                            row.update(ok=False, message=self.secrets.redact(ex)[:160])
            out.append(row)
        return {"role": role, "results": out}

    # ---------------------------------------------------------------- usage
    def usage_by_model(self, name):
        rows = costlog.read_log(self.pdir(name))
        agg = {}
        for r in rows:
            k = (r.get("provider") or "", r.get("model") or "")
            a = agg.setdefault(k, {"provider": k[0], "model": k[1], "cost": 0.0, "calls": 0})
            a["cost"] += float(r.get("cost") or 0)
            a["calls"] += 1
        return {"rows": sorted(({**v, "cost": round(v["cost"], 6)} for v in agg.values()), key=lambda x: -x["cost"])}
