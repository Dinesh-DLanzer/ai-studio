"""Verification, AI settings, model catalog, and background linting domain."""
from datetime import datetime
import json
import os
from pathlib import Path
import threading
import time
import urllib.request

from aistudio import aisettings, character_check, chat as chat_mod, costlog, languages as lang_mod, project as project_mod, project_lock, pricing as pricing_mod, roles as roles_mod, verify as verify_mod
from aistudio.domain.common import ServiceError
from aistudio.providers import base as pbase, config as pconf


class VerifyDomain:
    VERIFY_DELAY = 1.5

    def __init__(self, ws):
        self.ws = ws

    def _legacy_view(self):
        self.ws.ensure_settings()
        doc, out = pconf.load_roles(self.ws.settings_dir), aisettings.defaults()
        types = {p["id"]: p["type"] for p in pconf.load_providers(self.ws.settings_dir)}
        for r in aisettings.ROLES:
            ms = [c["model"] for c in doc["roles"][r]["chain"] if types.get(c["provider"]) == "openrouter"]
            if ms:
                out[r] = {"models": ms}
        for k in ("allow_paid", "ai_cap_usd", "auto_verify"):
            out[k] = doc[k]
        return out

    def ai_settings(self):
        stored = self._legacy_view()
        eff, locked = aisettings.effective(stored)
        return {"settings": eff, "stored": stored, "locked": locked}

    def put_ai_settings(self, new):
        errs = aisettings.validate(new) if isinstance(new, dict) else ["settings must be an object"]
        if errs:
            raise ServiceError("; ".join(errs))
        self.ws.ensure_settings()
        provs = pconf.load_providers(self.ws.settings_dir)
        if not any(x["type"] == "openrouter" for x in provs):
            provs.insert(0, {"id": "openrouter", "type": "openrouter", "label": "OpenRouter", "base_url": "", "enabled": True})
            pconf.save_providers(self.ws.settings_dir, provs)
        orid = next(x["id"] for x in provs if x["type"] == "openrouter")
        doc = pconf.load_roles(self.ws.settings_dir)
        types = {x["id"]: x["type"] for x in provs}
        for r in aisettings.ROLES:
            keep = [c for c in doc["roles"][r]["chain"] if types.get(c["provider"]) != "openrouter"]
            doc["roles"][r]["chain"] = [{"provider": orid, "model": m} for m in new[r]["models"]] + keep
        for k in ("allow_paid", "ai_cap_usd", "auto_verify"):
            doc[k] = new[k]
        try:
            pconf.save_roles(self.ws.settings_dir, doc, provs)
        except ValueError as e:
            raise ServiceError(str(e)) from None
        return self.ai_settings()

    def ai_catalog(self, refresh=False):
        """Text models from OpenRouter with prices (free first). Falls back to the built-in free list when offline."""
        now = time.time()
        if self.ws._catalog_cache and not refresh and now - self.ws._catalog_cache[0] < 600:
            return self.ws._catalog_cache[1]
        rows, source = aisettings.static_catalog(), "built-in free list (could not reach OpenRouter)"
        try:
            if self.ws.catalog_fetch:
                data = self.ws.catalog_fetch()
            elif os.environ.get("AISTUDIO_NO_NETWORK") == "1":
                raise OSError("network disabled")
            else:
                data = json.load(urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=20))
            live = aisettings.parse_catalog(data)
            if live:
                rows, source = live, "live from OpenRouter"
        except Exception:
            pass
        out = {"models": rows[:500], "source": source}
        self.ws._catalog_cache = (now, out)
        return out

    def ai_spent(self, name):
        return round(sum(float(r["cost"] or 0) for r in costlog.read_log(self.ws.pdir(name)) if r["stage"] in ("chat", "verify")), 6)

    def _ai_call(self, name, role, messages):
        """The ONE place a text AI model is called (chat and verify roles)."""
        p = self.ws.pdir(name)
        cfg = self.ai_settings()["settings"]
        runner = self.ws.runner()
        free = lambda e: bool(e["card"] and e["card"].get("kind") == "text" and e["card"].get("free"))
        entries = [e for e in runner.resolve(role, p) if e["problem"] is None]
        paid = any(not free(e) for e in entries)
        planned = max((float((e.get("card") or {}).get("per_call") or
                            (8192 * float((e.get("card") or {}).get("output_per_1m") or 0) / 1_000_000))
                       for e in entries if not free(e)), default=0.0)
        unpriced_paid = any(not free(e) and not (e.get("card") or {}).get("per_call") and not (e.get("card") or {}).get("output_per_1m") for e in entries)
        allow = lambda e: (True, "") if free(e) or cfg["allow_paid"] else (False, "paid or unpriced model; turn on 'Allow paid models' (or set it as free) in Settings")
        try:
            with project_lock.lock(p):
                if paid and (self.ai_spent(name) + planned > cfg["ai_cap_usd"] or (cfg["allow_paid"] and unpriced_paid)):
                    raise ServiceError(f"The AI spending cap for this project (${cfg['ai_cap_usd']:.2f}) would be exceeded by this call. Raise it in AI settings or switch to a free model.")
                res = runner.chat(role, messages, {"max_tokens": 8192, "temperature": 0.4}, project_dir=p, allow=allow)
                if paid or res.get("cost"):
                    attempt = 1 + len([r for r in costlog.read_log(p) if r["stage"] == role])
                    costlog.append_log(p, {"timestamp": datetime.now().isoformat(timespec="seconds"), "shot": "_ai", "stage": role,
                        "model": res["model"], "resolution": "", "seconds": "", "attempt": str(attempt), "job_id": "",
                        "cost": res.get("cost", 0), "result": "completed", "provider": res.get("provider", ""),
                        "cost_source": res.get("cost_source", ""), "actor": "local"})
        except (pbase.ProviderError, roles_mod.ChainError, ValueError) as e:
            raise ServiceError(f"The {role} model is unavailable: {e}") from None
        return res

    def languages(self):
        return [{"name": n, "tested": lang_mod.LANGUAGES[n][1], "script": bool(lang_mod.LANGUAGES[n][0])} for n in lang_mod.NAMES]

    def _verify_inputs(self, p, scope):
        brief = self.ws._read(p, "brief.json", {})
        shots = self.ws._read(p, "shots.json", {"shots": []})
        imgs = self.ws._read(p, "images.json", {"images": []})
        lang = lang_mod.canonical(brief.get("language") or shots.get("language") or "")
        stills = {f.name.rsplit(".", 1)[0] for f in (p / "stills").glob("*") if f.is_file()}
        if scope == "brief":
            art, rules = brief, verify_mod.lint_brief(brief, lang, chat_mod.progress(brief)["missing"])
        elif scope == "story":
            md = (p / "Story.md").read_text(encoding="utf-8") if (p / "Story.md").exists() else ""
            art, rules = {"Story.md": md[:9000]}, verify_mod.lint_story(md, brief, lang)
        elif scope == "assets":
            art, rules = {"images": imgs, "files_present": sorted(stills)}, verify_mod.lint_assets(imgs, stills, brief)
        elif scope == "shots":
            art, rules = shots, verify_mod.lint_shots(shots, imgs, stills, lang) + character_check.drift_findings(p, [s["id"] for s in shots.get("shots", [])])
        elif scope == "todos":
            art = self.ws._todo_store(p)
            rules = verify_mod.lint_todos(art)
        else:
            raise ServiceError(f"unknown scope {scope}; use one of {', '.join(verify_mod.SCOPES)}")
        return art, rules, lang, brief, verify_mod.content_hash(art, lang)

    def _verify_ai(self, name, scope, art, brief, lang, rules):
        if self.ws.is_test(self.ws.pdir(name)):
            return {"status": "ok", "findings": [], "source": "ai", "model": "fake/reviewer", "summary": "Test pipeline: no AI reviewer (rule checks only)"}
        try:
            res = self._ai_call(name, "verify", verify_mod.build_ai_messages(scope, art, brief, lang, rules))
        except ServiceError as e:
            return {"status": "ok", "findings": [], "source": "ai", "model": "", "summary": f"AI review unavailable: {e}", "error": str(e)}
        parsed = verify_mod.parse_ai(res["text"])
        out = verify_mod.result(parsed["findings"], "ai", res["model"], parsed["summary"] or "AI review done")
        if not parsed["ok"]:
            out["error"] = parsed["summary"]
        return out

    def verify_run(self, name, scope, ai=True):
        p = self.ws.pdir(name)
        art, rules, lang, brief, h = self._verify_inputs(p, scope)
        store = self.ws._read(p, "verify.json", {})
        entry = {"hash": h, "when": datetime.now().isoformat(timespec="seconds"), "ai": None}
        if ai:
            entry["ai"] = self._verify_ai(name, scope, art, brief, lang, rules)
        else:
            entry["ai"] = (store.get(scope) or {}).get("ai") if (store.get(scope) or {}).get("hash") == h else None
        store[scope] = entry
        project_mod.save_json(p, "verify.json", store)
        return self.verify_status(name)[scope]

    def verify_status(self, name):
        """Rules are recomputed fresh every time (free). The stored AI result is shown only while the content is unchanged (else `stale`)."""
        p = self.ws.pdir(name)
        store = self.ws._read(p, "verify.json", {})
        out = {}
        for scope in verify_mod.SCOPES:
            art, rules, lang, brief, h = self._verify_inputs(p, scope)
            saved = store.get(scope) or {}
            ai = saved.get("ai") if saved.get("hash") == h else None
            rr = verify_mod.result(rules)
            findings = [{**x, "source": "rules"} for x in rr["findings"]] + [{**x, "source": "ai"} for x in (ai or {}).get("findings", [])]
            rank = {"ok": 0, "warn": 1, "fail": 2}
            status = max([rr["status"], (ai or {}).get("status", "ok")], key=lambda x: rank[x])
            out[scope] = {
                "status": status,
                "findings": findings,
                "rules": rr["status"],
                "ai": None if ai is None else {k: ai.get(k) for k in ("status", "model", "summary", "error")},
                "ai_stale": bool(saved.get("ai")) and saved.get("hash") != h,
                "when": saved.get("when"),
                "running": (name, scope) in self.ws._verify_running,
            }
        return out

    def _changed(self, name, *scopes):
        """Called after every modification. With auto_verify on (web server) the AI review runs in the background for changed content."""
        if not self.ws.auto_verify:
            return
        for scope in scopes:
            key = (name, scope)
            with self.ws._verify_lock:
                if key in self.ws._verify_running:
                    continue
                self.ws._verify_running.add(key)
            threading.Thread(target=self._verify_bg, args=(name, scope), daemon=True).start()

    def _verify_bg(self, name, scope):
        try:
            time.sleep(self.VERIFY_DELAY)
            p = self.ws.pdir(name)
            if not self.ai_settings()["settings"]["auto_verify"]:
                return
            entries = [e for e in self.ws.runner().resolve("verify", p) if e["problem"] is None]
            if not entries or any(not self.ws.pricing().is_free(entry.get("card")) for entry in entries):
                return
            _, _, _, _, h = self._verify_inputs(p, scope)
            saved = self.ws._read(p, "verify.json", {}).get(scope) or {}
            if saved.get("hash") == h and saved.get("ai"):
                return
            self.verify_run(name, scope, ai=True)
        except Exception:
            pass
        finally:
            with self.ws._verify_lock:
                self.ws._verify_running.discard((name, scope))

    def verify_now(self, name, scope):
        """User pressed Re-check: run rules + AI in the background right away."""
        self.ws.pdir(name)
        if scope not in verify_mod.SCOPES:
            raise ServiceError(f"unknown scope {scope}")
        key = (name, scope)
        with self.ws._verify_lock:
            if key in self.ws._verify_running:
                return {"running": True}
            self.ws._verify_running.add(key)

        def work():
            try:
                self.verify_run(name, scope, ai=True)
            except Exception:
                pass
            finally:
                with self.ws._verify_lock:
                    self.ws._verify_running.discard(key)

        threading.Thread(target=work, daemon=True).start()
        return {"running": True}

    def wait_verify(self, timeout=10.0):
        t0 = time.time()
        while self.ws._verify_running and time.time() - t0 < timeout:
            time.sleep(0.05)
