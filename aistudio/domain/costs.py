"""Costs, pricing, budget estimation and job sync domain."""
import csv
from datetime import datetime
import json

from aistudio import budget as budget_mod, costlog, pricing as pricing_mod, project as project_mod, roles as roles_mod
from aistudio.domain.common import ServiceError
from aistudio.providers import base as pbase


class CostDomain:
    def __init__(self, ws):
        self.ws = ws

    def rates(self):
        return json.loads(self.ws.rates_path.read_text(encoding="utf-8"))

    def estimate(self, name, failure=0.2):
        p = self.ws.pdir(name)
        shots, images = self.ws._read(p, "shots.json"), self.ws._read(p, "images.json", {"images": []})
        existing = {i["id"] for i in images["images"] if (p / i["out"]).exists()}
        try:
            est = self._estimate(p, shots, images, existing, failure)
        except (KeyError, ValueError) as e:
            raise ServiceError(f"cannot estimate: {e}") from None
        b = {**est, "approved": False, "created": datetime.now().isoformat(timespec="seconds")}
        project_mod.save_json(p, "budget.json", b)
        return b

    def _estimate(self, p, shots, images, existing, failure):
        """Budget estimate priced with the primary model of the video chain (and the image chain, when there is one)."""
        e = self.ws._primary("video", p)
        if not e["card"] or e["card"].get("kind") != "video":
            raise ServiceError(f"No price set for {e['model']}. Set it in Settings > Model Configuration.")
        k = pricing_mod.key(e["provider"]["id"], e["model"])
        doc = {**shots, "shots": [{**s, "model": k} for s in shots["shots"]]}
        image_rate = 0.036
        try:
            ie = self.ws._primary("image", p)
            rate = self.ws.pricing().image_price(ie["card"])
            image_rate = image_rate if rate is None else rate
        except ServiceError:
            pass
        return budget_mod.estimate(doc, images, {"models": {k: e["card"]["per_second"]}}, existing, failure, image_rate=image_rate)

    def approve_budget(self, name):
        """Human channel only (web UI / terminal). Not exposed through MCP."""
        p = self.ws.pdir(name)
        b = self.ws._read(p, "budget.json") or (_ for _ in ()).throw(ServiceError("run estimate first"))
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
