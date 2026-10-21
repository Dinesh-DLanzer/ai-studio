"""Fixed batch plans ("Generate all"): the plan a human approves is the plan that runs.

A batch freezes the list of items with their model, price and a digest of the request specification. A HUMAN approves the batch
(web session, MCP elicitation or the out-of-band code; never an API key or chat). The server then runs the items one after another
through the normal pipeline: for each item it re-checks model, price and digest, creates the item's own proposal, pre-approves it
(that is what the batch approval authorises, at exactly that price) and executes it, so every item still passes the budget,
stop-loss and attempt gates and consumes its own grant. Any change stops that item as needs_reapproval; finished items stay done.

The digest covers the specification (prompt, seconds, resolution, audio, refs, first frame id). It cannot cover the bytes of files
that earlier items of the same batch create; those are pinned by each item's own proposal at run time.
"""
import hashlib
import json
import os
import secrets
import time
from pathlib import Path

from aistudio import approvals, costlog, project_lock
from aistudio.domain.common import ServiceError, _ident
from aistudio.domain.pipeline import MAX_VARIANTS

DIR = "batches"
ACTIVE = ("approved", "running")


def _canon(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def batch_hash(items, total):
    keep = [{k: it[k] for k in ("kind", "target", "model", "price", "request_hash")} for it in items]
    return hashlib.sha256(_canon({"items": keep, "total": round(float(total), 6)}).encode("utf-8")).hexdigest()


class BatchDomain:
    def __init__(self, ws):
        self.ws = ws

    # ---- storage
    def _path(self, name, bid):
        return self.ws.pdir(name) / DIR / f"{_ident(bid, 'batch id')}.json"

    def _save(self, name, batch):
        path = self._path(name, batch["id"])
        path.parent.mkdir(exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(batch, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    def get(self, name, bid):
        path = self._path(name, bid)
        if not path.is_file():
            raise ServiceError(f"unknown batch {bid}")
        try:
            batch = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            raise ServiceError(f"batch {bid} is unreadable") from None
        if not isinstance(batch, dict) or batch.get("batch_hash") != batch_hash(batch.get("items", []), batch.get("total", 0)):
            raise ServiceError(f"batch {bid} was altered after it was created; create a new one")
        return batch

    def list(self, name):
        out = []
        for f in sorted((self.ws.pdir(name) / DIR).glob("*.json")):
            try:
                b = self.get(name, f.stem)
                out.append({k: b[k] for k in ("id", "status", "total", "created", "actor") if k in b} | {"items": len(b["items"])})
            except ServiceError:
                out.append({"id": f.stem, "status": "invalid"})
        return out

    # ---- request digest
    def digest(self, p, kind, target, model, price, variant=None):
        """Hash of the request specification as written in shots.json / images.json (files need not exist yet)."""
        if kind == "image":
            doc = self.ws._read(p, "images.json", {"images": []})
            spec = next((i for i in doc["images"] if i["id"] == target), None)
            if spec is None:
                raise ServiceError(f"unknown image id {target}")
            body = {"style": doc.get("style", ""), "spec": {k: spec.get(k) for k in ("id", "kind", "out", "prompt", "refs", "aspect_ratio")}}
            if variant:
                body["variant"] = variant
        else:
            shot, doc, res, audio, ff = self.ws._clip_spec_loose(p, target)
            body = {"prompt": shot["prompt"], "seconds": shot["seconds"], "resolution": res, "audio": audio, "first_frame": ff,
                    "aspect_ratio": doc.get("aspect_ratio", "9:16")}
            if shot.get("end_frame"):
                body["end_frame"] = shot["end_frame"]
            for k in ("direction", "camera", "keyframes"):      # content the human approved with the batch total: an edit before run is a change
                if shot.get(k):
                    body[k] = shot[k]
            if variant:
                body["variant"] = variant
        return approvals.request_hash(kind, target, model, price, body)

    # ---- lifecycle
    def create(self, name, actor="local", only=None, plan=None):
        """Freeze the current Generate-all plan (or just the (kind, target) pairs in `only`, used by crew runs, or an explicit `plan` of the
        same shape such as an identity sheet). Free: creates a file only; every item keeps its own price, hash, proposal and cost-log row."""
        p = self.ws.pdir(name)
        plan = plan or self.ws.generate_all_plan(name)
        if only is not None:
            plan["items"] = [it for it in plan["items"] if (it["kind"], it["target"]) in only]
            if not plan["items"]:
                raise ServiceError("none of the proposed items can be batched right now")
        items = [{"kind": it["kind"], "target": it["target"], "label": it.get("label", ""), "model": it["model"], "price": round(float(it["price"]), 6),
                  "request_hash": it["request_hash"] if it.get("recipe") else self.digest(p, it["kind"], it["target"], it["model"], it["price"], it.get("variant")),
                  "status": "pending", **({"variant": it["variant"]} if it.get("variant") else {}),
                  **({"recipe": it["recipe"]} if it.get("recipe") else {})} for it in plan["items"]]      # recipe items carry their own request hash (aistudio/recipes.py)
        total = round(sum(it["price"] for it in items), 6)
        batch = {"id": secrets.token_hex(6), "items": items, "total": total, "batch_hash": batch_hash(items, total), "status": "awaiting_approval",
                 "created": time.time(), "actor": actor, "budget": plan["budget"], **(plan.get("extra") or {})}
        self._save(name, batch)
        return batch

    def create_variants(self, name, kind, target, count, actor="local"):
        """N candidates of one still or clip as N SEPARATE items of ONE awaiting-approval batch: each has its own price, request hash, proposal,
        grant, stop-loss check and cost-log row, and total == N x unit price (shown up front). One approval of the batch authorises exactly these."""
        if kind not in ("image", "clip"):
            raise ServiceError("variants are for images and clips")
        if not isinstance(count, int) or isinstance(count, bool) or not 2 <= count <= MAX_VARIANTS:
            raise ServiceError(f"variants must be a whole number from 2 to {MAX_VARIANTS}")
        p = self.ws.pdir(name)
        price, model = self.ws.pipeline_domain._item_price(p, kind, target)
        b = self.ws._read(p, "budget.json", {})
        items = [{"kind": kind, "target": target, "label": f"{target} v{k}", "price": price, "model": model, "variant": k} for k in range(1, count + 1)]
        plan = {"items": items, "total": round(price * count, 6),
                "budget": {"estimate": b.get("estimate"), "stop_loss": b.get("stop_loss"), "spent": round(costlog.spent(p), 6)}}
        return self.create(name, actor=actor, plan=plan)

    def approve(self, name, bid, expected_hash):
        """HUMAN channel only. The caller must name the batch_hash it showed the human, so the approval is of exactly that plan."""
        batch = self.get(name, bid)
        if batch["status"] != "awaiting_approval":
            raise ServiceError(f"batch is {batch['status']}")
        if expected_hash != batch["batch_hash"]:
            raise ServiceError("batch_hash does not match this batch; show the human the current plan")
        batch.update(status="approved", approved_at=time.time())
        self._save(name, batch)
        return batch

    def run(self, name, bid, on_item=None):
        """Run an approved batch, item by item, stopping at the first problem. Returns the final batch."""
        p = self.ws.pdir(name)
        with project_lock.lock(p):
            batch = self.get(name, bid)
            if batch["status"] != "approved":
                raise ServiceError(f"batch is {batch['status']}; only an approved batch can run")
            batch["status"] = "running"
            self._save(name, batch)
        try:
            for item in batch["items"]:
                if item["status"] == "done":
                    continue
                item["status"] = "running"
                self._save(name, batch)
                if on_item:
                    on_item(item, "start")   # the job ledger records one child job per item
                if item.get("recipe"):
                    from aistudio import recipes
                    stop = recipes.run_item(self.ws, name, p, item, batch)
                else:
                    stop = self._run_item(name, p, item)
                self._save(name, batch)
                if on_item:
                    on_item(item, "end")
                if stop:
                    batch["status"] = stop
                    return batch
            batch["status"] = "done"
            return batch
        except BaseException as error:
            batch["status"] = "error"
            batch["error"] = str(error)
            raise
        finally:
            self._save(name, batch)

    def _run_item(self, name, p, item):
        """Run one item; returns None on success or the batch status to stop with."""
        try:
            price, model = self.ws.pipeline_domain._item_price(p, item["kind"], item["target"])
            changes = []
            if model != item["model"]:
                changes.append(f"model {item['model']} -> {model}")
            if round(float(price), 6) != item["price"]:
                changes.append(f"price ${item['price']:.3f} -> ${float(price):.3f}")
            if self.digest(p, item["kind"], item["target"], model, price, item.get("variant")) != item["request_hash"]:
                changes.append("request changed")
        except ServiceError as error:
            item.update(status="error", error=str(error))
            return "error"
        if changes:
            item.update(status="needs_reapproval", changes=changes)
            return "needs_reapproval"
        try:
            prop = self.ws.propose(name, item["kind"], item["target"], options={"variant": item["variant"]} if item.get("variant") else None)
            if prop["model"] != item["model"] or prop["price"] != item["price"]:
                self.ws.reject(name, prop["id"])
                item.update(status="needs_reapproval", changes=["model or price changed while starting"])
                return "needs_reapproval"
            self.ws.approve_human(name, prop["id"])  # authorised by the human's batch approval, at exactly this price
            res = self.ws.execute(name, prop["id"])
        except ServiceError as error:
            item.update(status="error", error=str(error))
            return "error"
        if isinstance(res, dict) and res.get("error"):
            item.update(status="error", error=str(res["error"]), proposal=prop["id"])
            return "error"
        item.update(status="done", proposal=prop["id"], cost=(res or {}).get("cost"))
        return None
