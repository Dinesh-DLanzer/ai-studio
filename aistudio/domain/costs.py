"""Costs, pricing, budget estimation and job sync domain."""
import csv
from datetime import datetime
import hashlib
import json

from aistudio import budget as budget_mod, costlog, pricing as pricing_mod, project as project_mod, roles as roles_mod
from aistudio.domain import spec as spec_mod
from aistudio.domain.common import ServiceError
from aistudio.providers import base as pbase


class BudgetStale(ServiceError):
    """The approved budget no longer matches the plan; .diff is the structured difference for the UI."""

    def __init__(self, diff):
        est = lambda v: "?" if v is None else f"${v:.2f}"
        super().__init__(f"Budget out of date: estimate now {est(diff['new_estimate'])} (approved {est(diff['approved_estimate'])}). Re-approve.")
        self.diff = diff


class CostDomain:
    def __init__(self, ws):
        self.ws = ws

    def plan_snapshot(self, p):
        """Only what changes price or count. Prompt wording is excluded: each proposal binds its prompt via request_hash."""
        shots = self.ws._read(p, "shots.json", {"shots": []})
        images = self.ws._read(p, "images.json", {"images": []})
        res, audio = shots.get("final_resolution", "720p"), shots.get("audio", False)
        return {
            "shots": {s["id"]: {"seconds": s.get("seconds"), "resolution": s.get("resolution") or res, "audio": s.get("audio", audio), "model": s.get("model")}
                      for s in shots.get("shots", [])},
            "images": {i["id"]: {"kind": i.get("kind"), "refs": len(i.get("refs", []))} for i in images.get("images", [])},
        }

    def fingerprints(self, p):
        """Return hashes binding a budget approval to the current plan and price cards."""
        roles = {}
        for role in ("image", "video", "vision"):
            try:
                roles[role] = [{"provider": e["provider"].get("id"), "model": e["model"], "card": e.get("card")} for e in self.ws.runner().resolve(role, p)]
            except Exception:
                roles[role] = []
        try:      # models picked per shot / image: a price change there must stale the approval too
            extra = {}
            for kind, items in (("clip", self.ws._read(p, "shots.json", {"shots": []}).get("shots", [])), ("image", self.ws._read(p, "images.json", {"images": []}).get("images", []))):
                for item in items:
                    if item.get("model"):
                        sp = spec_mod.resolve(self.ws, p, kind, item["id"], loose=True)
                        if sp.explicit:
                            extra[f"{kind}:{item['id']}"] = {"provider": sp.provider, "model": sp.model, "card": sp.entry.get("card")}
            if extra:
                roles["per_item"] = extra
        except ServiceError:
            roles["per_item"] = "unresolvable"
        canon = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return {
            "plan_hash": hashlib.sha256(canon(self.plan_snapshot(p))).hexdigest(),
            "pricing_hash": hashlib.sha256(canon(roles)).hexdigest(),
        }

    @staticmethod
    def plan_diff(old, new):
        """Per-field differences between two plan snapshots, for the approve dialog."""
        out = []
        for kind in ("shots", "images"):
            o, n = old.get(kind, {}), new.get(kind, {})
            if len(o) != len(n):
                out.append({"field": f"{kind}_count", "id": "", "from": len(o), "to": len(n)})
            for k in sorted(set(o) | set(n)):
                if k not in o or k not in n:
                    out.append({"field": kind[:-1], "id": k, "from": "present" if k in o else None, "to": "present" if k in n else None})
                    continue
                for field in sorted(set(o[k]) | set(n[k])):
                    if o[k].get(field) != n[k].get(field):
                        out.append({"field": "refs" if field == "refs" else field, "id": k, "from": o[k].get(field), "to": n[k].get(field)})
        return out

    def stale_budget(self, p, b):
        """None when the approval still matches the plan and prices, else a structured diff (legacy budgets without hashes pass)."""
        if not b.get("plan_hash"):
            return None
        now = self.fingerprints(p)
        if b.get("plan_hash") == now["plan_hash"] and b.get("pricing_hash") == now["pricing_hash"]:
            return None
        diff = self.plan_diff(b.get("plan") or {}, self.plan_snapshot(p)) if b.get("plan") else []
        if b.get("pricing_hash") != now["pricing_hash"]:
            diff.append({"field": "pricing", "id": "", "from": "approved price cards", "to": "current price cards"})
        try:
            current = self._current_estimate(p)["estimate"]
        except (ServiceError, KeyError, ValueError):
            current = None
        return {"changes": diff, "approved_estimate": b.get("estimate"), "new_estimate": current}

    def rates(self):
        return json.loads(self.ws.rates_path.read_text(encoding="utf-8"))

    def _current_estimate(self, p, failure=0.2):
        shots, images = self.ws._read(p, "shots.json"), self.ws._read(p, "images.json", {"images": []})
        existing = {i["id"] for i in images["images"] if (p / i["out"]).exists()}
        return self._estimate(p, shots, images, existing, failure)

    def estimate(self, name, failure=0.2):
        p = self.ws.pdir(name)
        try:
            est = self._current_estimate(p, failure)
        except (KeyError, ValueError) as e:
            raise ServiceError(f"cannot estimate: {e}") from None
        b = {**est, "approved": False, "created": datetime.now().isoformat(timespec="seconds"), **self.fingerprints(p), "plan": self.plan_snapshot(p)}
        project_mod.save_json(p, "budget.json", b)
        return b

    def _estimate(self, p, shots, images, existing, failure):
        """Budget estimate: every clip priced from its own GenerationSpec (the shot's model, snapped seconds), stills from the image model."""
        rates, priced = {}, []
        for s in shots["shots"]:
            sp = spec_mod.resolve(self.ws, p, "clip", s["id"], loose=True)
            k = pricing_mod.key(sp.provider, sp.model)
            rates[k] = sp.entry["card"]["per_second"]
            priced.append({**s, "model": k, "seconds": sp.seconds, "resolution": sp.resolution, "audio": sp.audio, "price": sp.price})
        todo = [i for i in images["images"] if i["id"] not in existing]
        image_total = 0.0
        for i in todo:
            try:
                sp = spec_mod.resolve(self.ws, p, "image", i["id"], loose=True)
                image_total += sp.price
            except ServiceError:      # no usable image model or price: the old flat default
                image_total += 0.036
        image_rate = image_total / len(todo) if todo else 0.036
        return budget_mod.estimate({**shots, "shots": priced}, images, {"models": rates}, existing, failure, image_rate=image_rate)

    def approve_budget(self, name):
        """Human channel only (web UI / terminal). Not exposed through MCP."""
        p = self.ws.pdir(name)
        b = self.ws._read(p, "budget.json") or (_ for _ in ()).throw(ServiceError("run estimate first"))
        if not b.get("plan_hash") or not b.get("pricing_hash"):
            b.update(self.fingerprints(p), plan=self.plan_snapshot(p))
        b["approved"] = True
        project_mod.save_json(p, "budget.json", b)
        return b

    def set_max_attempts(self, name, max_attempts):
        p = self.ws.pdir(name)
        b = self.ws._read(p, "budget.json") or {}
        b["max_attempts"] = int(max_attempts)
        project_mod.save_json(p, "budget.json", b)
        return {"ok": True, "max_attempts": b["max_attempts"]}

    def costs(self, name):
        p = self.ws.pdir(name)
        return {"split": costlog.split(p), "rows": costlog.read_log(p), "budget": self.ws._read(p, "budget.json", {})}

    def sync(self, name):
        """Resolve clips left pending by a timeout: fetch real status/cost and save the clip."""
        p = self.ws.pdir(name)
        rows, fixed = costlog.read_log(p), []
        for r in rows:
            if r["result"] == "pending" and r["job_id"]:
                req = {"seconds": int(r["seconds"] or 0), "resolution": r["resolution"] or "720p", "audio": False}
                try:
                    res = self.ws.runner().fetch_video({"job_id": r["job_id"], "model": r["model"], "provider": r.get("provider") or "openrouter"}, req)
                except (roles_mod.ChainError, pbase.ProviderError):
                    continue
                if res["status"] == "pending":
                    continue
                r["cost"] = res.get("cost", 0)
                r["cost_source"] = res.get("cost_source", "")
                r["result"] = "failed" if res["status"] == "failed" else "completed"
                if res["status"] == "done":
                    (p / "clips" / f"{r['shot']}_final_a{r['attempt']}.mp4").write_bytes(res["bytes"])
                fixed.append(r["shot"])
        if fixed:
            with (p / "cost_log.csv").open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=costlog.LOG_COLS)
                w.writeheader()
                w.writerows(rows)
        return {"resolved": fixed}
