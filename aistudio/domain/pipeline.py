"""Pipeline domain: proposals, approvals, execution, batch generation and review logic."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import shutil
import tempfile

from aistudio import activity, approvals, chat as chat_mod, costlog, editor as editor_mod, frames as frames_mod, gates, palette as palette_mod, project as project_mod, project_lock, roles as roles_mod
from aistudio.domain.costs import BudgetStale
from aistudio.domain.common import REVIEW_PRICE, ServiceError, _ident, _sha
from aistudio.providers import base as pbase
from aistudio import character_check
from aistudio.vision import clip_checklist, image_checklist


class PipelineDomain:
    def __init__(self, ws):
        self.ws = ws

    def _production(self, p):
        """Facts read from the project's files: brief progress, story, budget, every asset (made or not), uploads with their colours, every shot."""
        brief = self.ws._read(p, "brief.json", {})
        shots_doc = self.ws._read(p, "shots.json", {"shots": []})
        imgs = self.ws._read(p, "images.json", {"style": "", "images": []})
        budget = self.ws._read(p, "budget.json", {})
        assets, uploads = [], []
        for i in imgs.get("images", []):
            made = (p / i["out"]).is_file()
            if i.get("kind") == "other":
                uploads.append({"id": i["id"], "file": Path(i["out"]).name, "made": made, "colors": palette_mod.dominant_colors(p / i["out"]) if made else []})
            else:
                assets.append({"id": i["id"], "kind": i["kind"], "made": made, "refs": i.get("refs", [])})
        shots = []
        for sh in shots_doc.get("shots", []):
            clip = editor_mod.clip_for_shot(p, sh)
            shots.append({"id": sh["id"], "clip": bool(clip), "approved": bool(sh.get("final_ok")), "first_frame": Path(sh["first_frame"]).stem if sh.get("first_frame") else ""})
        return {
            "brief": brief,
            "progress": chat_mod.progress(brief),
            "story": {"shots": len(shots), "pending": (p / "pending_story.md").exists(), "style": imgs.get("style", "")},
            "budget": {"estimate": budget.get("estimate"), "approved": bool(budget.get("approved"))},
            "assets": assets,
            "uploads": uploads,
            "shots": shots,
            "spent": round(costlog.spent(p), 3),
        }

    def production_progress(self, name):
        """The production checklist for the chat page: groups with counts, and the ONE next action."""
        st = self._production(self.ws.pdir(name))
        a, shots, pr = st["assets"], st["shots"], st["progress"]
        by = {k: [x for x in a if x["kind"] == k] for k in ("character", "background", "frame")}
        done = lambda xs: sum(1 for x in xs if x["made"])
        groups = [
            {"key": "brief", "label": "Brief", "done": pr["required_done"], "total": pr["required_total"]},
            {"key": "story", "label": "Storyboard", "done": 1 if shots else 0, "total": 1},
            {"key": "budget", "label": "Budget approved", "done": 1 if st["budget"]["approved"] else 0, "total": 1},
        ]
        for k, label in (("character", "Characters"), ("background", "Backgrounds"), ("frame", "Scene frames")):
            if by[k]:
                groups.append({"key": k, "label": label, "done": done(by[k]), "total": len(by[k])})
        if shots:
            groups.append({"key": "clip", "label": "Video clips", "done": sum(1 for x in shots if x["clip"]), "total": len(shots)})
            groups.append({"key": "approve", "label": "Clips approved", "done": sum(1 for x in shots if x["approved"]), "total": len(shots)})
        nxt = None
        if not pr["complete"]:
            nxt = {"kind": "chat", "label": "Answer Tara's questions"}
        elif st["story"]["pending"]:
            nxt = {"kind": "apply-story", "label": "Apply the drafted storyboard"}
        elif not shots:
            nxt = {"kind": "chat", "label": "Ask Tara to draft the storyboard"}
        elif not st["budget"]["approved"]:
            nxt = {"kind": "budget", "label": "Set and approve the budget"}
        else:
            ready = {x["id"] for x in a if x["made"]} | {u["id"] for u in st["uploads"] if u["made"]}
            todo = next((x for k in ("character", "background", "frame") for x in by[k] if not x["made"] and all(r in ready for r in x["refs"])), None)
            clip = next((x for x in shots if not x["clip"]), None)
            appr = next((x for x in shots if x["clip"] and not x["approved"]), None)
            if todo:
                nxt = {"kind": "image", "target": todo["id"], "label": f"Generate {todo['kind']} image: {todo['id']}"}
            elif any(not x["made"] for x in a):
                nxt = {"kind": "chat", "label": "Some images need another image first: check their references on the Assets page"}
            elif clip:
                nxt = {"kind": "clip", "target": clip["id"], "label": f"Generate video clip: {clip['id']}"}
            elif appr:
                nxt = {"kind": "approve", "target": appr["id"], "label": f"Watch and approve clip {appr['id']} on the Shots page"}
            else:
                nxt = {"kind": "export", "label": "Review & Export your video"}
        return {"groups": groups, "next": nxt, "queue": self._queue(st) if st["budget"]["approved"] and shots and pr["complete"] and not st["story"]["pending"] else []}

    @staticmethod
    def _queue(st):
        """Everything still to generate, in the only order that works: unmade images (characters, backgrounds, scene frames), then clips."""
        order = {"character": 0, "background": 1, "frame": 2}
        unmade = [x for x in st["assets"] if not x["made"]]
        by_id = {x["id"]: x for x in unmade}
        visited = set()
        visiting = set()
        imgs = []

        def visit(aid):
            if aid in visited or aid in visiting:
                return
            visiting.add(aid)
            node = by_id.get(aid)
            if node:
                for ref in node.get("refs", []):
                    if ref in by_id and ref not in visited:
                        visit(ref)
                visiting.remove(aid)
                visited.add(aid)
                imgs.append(node)

        for item in sorted(unmade, key=lambda x: order.get(x.get("kind"), 3)):
            visit(item["id"])

        items = [{"kind": "image", "target": x["id"], "label": f"{x['kind']} image: {x['id']}"} for x in imgs]
        items += [{"kind": "clip", "target": x["id"], "label": f"video clip: {x['id']}"} for x in st["shots"] if not x["clip"]]
        return items

    def generate_all_plan(self, name):
        """The exact price of every remaining image and clip (nothing is created or spent)."""
        p = self.ws.pdir(name)
        queue = self.production_progress(name)["queue"]
        if not queue:
            raise ServiceError("nothing is left to generate (or the budget is not approved yet)")
        items = []
        for it in queue:
            price, model = self._item_price(p, it["kind"], it["target"])
            items.append({**it, "price": price, "model": model})
        b = self.ws._read(p, "budget.json", {})
        total = round(sum(x["price"] for x in items), 6)
        spent = round(costlog.spent(p), 6)
        return {"items": items, "total": total, "budget": {"estimate": b.get("estimate"), "stop_loss": b.get("stop_loss"), "spent": spent}}

    def _item_price(self, p, kind, target):
        """(price, model) of one image or clip as the primary model would charge now; inputs need not exist yet."""
        if kind == "image":
            e = self.ws._primary("image", p)
            price = self.ws.pricing().image_price(e["card"])
            if price is None:
                raise ServiceError(f"No price set for {e['model']}. Set it in Settings > Model Configuration before generating images.")
            return price, e["model"]
        shot, doc, res, audio, _ = self._clip_spec_loose(p, target)
        e = self.ws._primary("video", p)
        price = self.ws.runner().video_price(e, {"seconds": shot["seconds"], "resolution": res, "audio": audio})
        if price is None:
            raise ServiceError(f"No price for {e['model']} at {res} ({shot['seconds']}s). Set it in Settings > Model Configuration.")
        return price, e["model"]

    def _clip_spec_loose(self, p, shot_id):
        """Like _clip_spec but the first frame may not exist yet (it is made earlier in the same run)."""
        doc = self.ws._read(p, "shots.json")
        shot = next((s for s in doc["shots"] if s["id"] == shot_id), None) or (_ for _ in ()).throw(ServiceError(f"unknown shot {shot_id}"))
        return shot, doc, shot.get("resolution") or doc.get("final_resolution", "720p"), shot.get("audio", doc.get("audio", False)), shot.get("first_frame")

    def _clip_spec(self, p, shot_id):
        doc = self.ws._read(p, "shots.json")
        shot = next((s for s in doc["shots"] if s["id"] == shot_id), None) or (_ for _ in ()).throw(ServiceError(f"unknown shot {shot_id}"))
        res = shot.get("resolution") or doc.get("final_resolution", "720p")
        audio = shot.get("audio", doc.get("audio", False))
        ff = shot.get("first_frame")
        if ff and not (p / ff).exists():
            raise ServiceError(f"first frame missing: {ff}")
        return shot, doc, res, audio, ff

    @staticmethod
    def _source_file(p, rel, label="source"):
        try:
            f = (p / str(rel)).resolve()
            f.relative_to(p.resolve())
        except (OSError, ValueError):
            raise ServiceError(f"{label} must stay inside the project") from None
        if not f.is_file():
            raise ServiceError(f"{label} not found: {rel}")
        return f

    def _payload_and_price(self, name, kind, target, options=None):
        p = self.ws.pdir(name)
        options = options or {}
        _ident(target, "target")
        if kind == "image":
            spec, refs, prompt = self.ws._image_spec(p, target)
            e = self.ws._primary("image", p)
            price = self.ws.pricing().image_price(e["card"])
            if price is None:
                raise ServiceError(f"No price set for {e['model']}. Set it in Settings > Model Configuration before generating images.")
            return {"prompt": prompt, "aspect_ratio": spec.get("aspect_ratio", "9:16"), "out": spec["out"], "provider": e["provider"]["id"],
                    "refs": [{"path": r.relative_to(p).as_posix(), "sha": _sha(r)} for r in refs]}, e["model"], price
        if kind == "clip":
            shot, doc, res, audio, ff = self._clip_spec(p, target)
            e = self.ws._primary("video", p)
            req = {"seconds": shot["seconds"], "resolution": res, "audio": audio}
            price = self.ws.runner().video_price(e, req)
            if price is None:
                raise ServiceError(f"No price for {e['model']} at {res} ({shot['seconds']}s). Set it in Settings > Model Configuration.")
            return {"prompt": shot["prompt"], "seconds": shot["seconds"], "audio": audio, "resolution": res, "provider": e["provider"]["id"],
                    "aspect_ratio": doc.get("aspect_ratio", "9:16"), "first_frame": ff, "first_frame_sha": _sha(p / ff) if ff else ""}, e["model"], price
        if kind == "image_edit":
            source = self._source_file(p, options.get("source"), "still")
            e = self.ws._primary("image", p)
            price = self.ws.pricing().image_price(e["card"])
            if price is None:
                raise ServiceError(f"No price set for {e['model']}. Set it in Settings > Model Configuration before editing stills.")
            return {"source": source.relative_to(p.resolve()).as_posix(), "source_sha": _sha(source), "prompt": str(options.get("prompt", "")),
                    "edit_mode": options.get("edit_mode", "inpaint_insertion"), "mask_mode": options.get("mask_mode", "MASK_MODE_BACKGROUND"),
                    "provider": e["provider"]["id"]}, e["model"], price
        if kind == "clip_extend":
            source = self._source_file(p, options.get("source"), "clip")
            seconds = int(options.get("seconds", 5))
            e = self.ws._primary("video", p)
            req = {"seconds": seconds, "resolution": "720p", "audio": False}
            price = self.ws.runner().video_price(e, req)
            if price is None:
                raise ServiceError(f"No price for {e['model']} at 720p ({seconds}s). Set it in Settings > Model Configuration.")
            return {"source": source.relative_to(p.resolve()).as_posix(), "source_sha": _sha(source), "prompt": str(options.get("prompt", "")),
                    "seconds": seconds, "aspect_ratio": "16:9", "resolution": "720p", "provider": e["provider"]["id"]}, e["model"], price
        if kind == "review":
            if options.get("review_type") == "character":
                f = self._source_file(p, options.get("file"), "character image")
                e = self.ws._primary("vision", p)
                return {"review_type": "character", "target": target, "file": f.relative_to(p.resolve()).as_posix(), "file_sha": _sha(f), "provider": e["provider"]["id"]}, e["model"], REVIEW_PRICE
            f = self._review_file(p, target)
            e = self.ws._primary("vision", p)
            payload = {"target": target, "file": f.resolve().relative_to(p.resolve()).as_posix(), "file_sha": _sha(f), "provider": e["provider"]["id"]}
            if f.suffix == ".mp4":
                shots = self.ws._read(p, "shots.json", {"shots": []})
                shot = next((s for s in shots["shots"] if s["id"] == target), {"id": target})
                payload["review_prompt"] = clip_checklist.build_prompt(shot, 8)
                payload["shot_spec"] = shot
                payload["first_frame_sha"] = _sha(p / shot["first_frame"]) if shot.get("first_frame") else ""
            else:
                imgs = self.ws._read(p, "images.json", {"images": []})
                spec = next((i for i in imgs["images"] if i["id"] == target), {"id": target})
                by = {i["id"]: i for i in imgs["images"]}
                refs = [(p / by[r]["out"]) for r in spec.get("refs", []) if r in by and (p / by[r]["out"]).exists()]
                payload["review_prompt"] = image_checklist.build_prompt(spec, [r.name for r in refs])
                payload["image_spec"] = {k: spec.get(k) for k in ("id", "kind", "out", "prompt", "refs", "aspect_ratio")}
                payload["refs"] = [{"path": r.resolve().relative_to(p.resolve()).as_posix(), "sha": _sha(r)} for r in refs]
            return payload, e["model"], REVIEW_PRICE
        raise ServiceError("kind must be image, clip, image_edit, clip_extend or review")

    def _review_file(self, p, target):
        rows = [r for r in costlog.read_log(p) if r["shot"] == target and r["stage"] == "final" and r["result"] == "completed"]
        if rows:
            return p / "clips" / f"{target}_final_a{rows[-1]['attempt']}.mp4"
        for ext in (".png", ".jpg"):
            if (p / "stills" / f"{target}{ext}").exists():
                return p / "stills" / f"{target}{ext}"
        raise ServiceError(f"nothing to review for {target}")

    def propose(self, name, kind, target, reveal_code=False, options=None):
        """Nothing is spent. reveal_code=True ONLY from the human-facing channel (web UI / terminal)."""
        p = self.ws.pdir(name)
        payload, model, price = self._payload_and_price(name, kind, target, options)
        summary = {"prompt": payload.get("prompt", "")[:400], "seconds": payload.get("seconds"), "audio": payload.get("audio"),
                   "first_frame": payload.get("first_frame"), "refs": [r["path"] for r in payload.get("refs", [])], "file": payload.get("file") or payload.get("source"),
                   "review_type": payload.get("review_type"), "provider": payload.get("provider")}
        return approvals.propose(p, kind, target, model, price, payload, reveal_code=reveal_code, summary=summary, options=options)

    def approve_human(self, name, pid):
        """HUMAN channel only (web UI / terminal). Never expose through MCP."""
        try:
            return approvals.approve_human(self.ws.pdir(name), pid)
        except approvals.ApprovalError as e:
            raise ServiceError(str(e)) from None

    def proposal_status(self, name, pid):
        try:
            return approvals.get(self.ws.pdir(name), pid)
        except approvals.ApprovalError as e:
            raise ServiceError(str(e)) from None

    def approve(self, name, pid, code):
        try:
            return approvals.approve(self.ws.pdir(name), pid, code)
        except approvals.ApprovalError as e:
            raise ServiceError(str(e)) from None

    def reject(self, name, pid):
        try:
            approvals.reject(self.ws.pdir(name), pid)
        except approvals.ApprovalError as e:
            raise ServiceError(str(e)) from None

    def execute(self, name, pid, override=False):
        p = self.ws.pdir(name)
        with project_lock.lock(p):
            try:
                prop = approvals.get(p, pid)
            except approvals.ApprovalError as e:
                raise ServiceError(str(e)) from None
            kind, target = prop["kind"], prop["shot"]
            payload, model, price = self._payload_and_price(name, kind, target, prop.get("options"))
            b = self.ws._read(p, "budget.json", {})
            stale = self.ws._costs.stale_budget(p, b)
            if stale:
                raise BudgetStale(stale)
            rows = costlog.read_log(p)
            stage = {"clip": "final", "image": "image", "image_edit": "image_edit", "clip_extend": "clip_extend", "review": "vision"}[kind]
            pending = [r for r in project_lock.read_reservations(p) if r.get("shot") == target and r.get("stage") == stage]
            attempted = {r["attempt"] for r in rows if r["shot"] == target and r["stage"] == stage}
            attempted.update(str(r["attempt"]) for r in pending)
            attempts = len(attempted)
            try:
                gates.check_run(b, costlog.spent(p) + project_lock.reserved(p), price, attempts if kind in ("clip", "image_edit", "clip_extend") else 0, override=override)
                request_digest = approvals.request_hash(kind, target, model, price, payload)
                grant = approvals.consume(p, pid, request_digest)
                project_lock.reserve(p, pid, price, actor=grant.actor, shot=target, stage=stage, attempt=attempts + 1,
                                     model=model, provider=payload.get("provider", ""))
            except (gates.GateError, approvals.ApprovalError) as e:
                raise ServiceError(str(e)) from None
            attempt = attempts + 1
            log = {"shot": target, "stage": stage, "model": model, "attempt": str(attempt), "job_id": "", "seconds": "", "provider": payload.get("provider", ""), "actor": grant.actor, "override": "yes" if override else "no"}
        activity.record_start(p, pid, kind, target, model, price, source="mcp")
        try:
            # Copy and verify every approved media input before handing it to an
            # adapter: neither file changes nor document rereads can change this call.
            with tempfile.TemporaryDirectory(prefix="aistudio-approved-") as tmp:
                inputs = Path(tmp)
                self._snapshot_inputs(p, inputs, payload)
                res = self._execute_kind(p, kind, target, payload, model, price, attempt, log, grant, inputs)
            activity.record_finish(p, pid, status="done", result=res)
            return res
        except roles_mod.NeedsNewApproval as e:
            activity.record_finish(p, pid, status="error", error=str(e))
            raise ServiceError(f"{e} Nothing was spent. Propose again to approve the new price.") from None
        except (roles_mod.ChainError, pbase.ProviderError) as e:
            activity.record_finish(p, pid, status="error", error=str(e))
            raise ServiceError(str(e)) from None
        except Exception as e:
            activity.record_finish(p, pid, status="error", error=str(e))
            raise
        finally:
            with project_lock.lock(p):
                logged = any(r.get("shot") == target and r.get("stage") == stage and r.get("attempt") == str(attempt)
                             for r in costlog.read_log(p))
                # Never erase evidence of possibly billed work if settlement failed.
                if logged or not approvals.get(p, pid).get("redeemed"):
                    project_lock.release(p, pid)

    @staticmethod
    def _snapshot_inputs(p, dest, payload):
        files = [(r["path"], r["sha"]) for r in payload.get("refs", [])]
        for path_key, hash_key in (("source", "source_sha"), ("file", "file_sha"), ("first_frame", "first_frame_sha")):
            if payload.get(path_key):
                files.append((payload[path_key], payload[hash_key]))
        shot = payload.get("shot_spec") or {}
        if shot.get("first_frame"):
            files.append((shot["first_frame"], payload["first_frame_sha"]))
        for rel, digest in files:
            source = PipelineDomain._source_file(p, rel)
            out = dest / rel
            if not out.resolve().is_relative_to(dest.resolve()):
                raise ServiceError("input must stay inside the project")
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, out)
            if _sha(out) != digest:
                raise ServiceError("input changed after approval; propose again")

    @staticmethod
    @contextmanager
    def _logged_output(p, row):
        """A paid result remains accounted for even when writing its output fails."""
        try:
            yield
        except BaseException:
            costlog.append_log(p, {**row, "result": "output_failed"})
            raise
        else:
            costlog.append_log(p, {**row, "result": "completed"})

    def _execute_kind(self, p, kind, target, payload, model, price, attempt, log, grant, inputs=None):
        inputs = inputs or p
        if kind == "image_edit":
            source = inputs / payload["source"]
            res = self.ws.runner().image_edit(source.as_posix(), payload["prompt"], edit_mode=payload["edit_mode"], mask_mode=payload["mask_mode"], project_dir=p, grant=grant)
            out = p / "stills" / f"{source.stem}_edit_a{attempt}.png"
            row = {**log, "model": res["model"], "provider": res["provider"], "cost_source": res["cost_source"], "timestamp": datetime.now().isoformat(timespec="seconds"), "resolution": "", "cost": res["cost"]}
            with self._logged_output(p, row):
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(res["bytes"])
            return {"kind": kind, "file": out.relative_to(p).as_posix(), "cost": res["cost"]}
        if kind == "clip_extend":
            source = inputs / payload["source"]
            res = self.ws.runner().video_extend(source.as_posix(), payload["prompt"], seconds=payload["seconds"], aspect_ratio=payload["aspect_ratio"], resolution=payload["resolution"], project_dir=p, grant=grant)
            job = res.get("job") or {}
            row = {**log, "model": res.get("model") or model, "provider": res.get("provider") or log["provider"], "cost_source": res.get("cost_source", ""),
                   "timestamp": datetime.now().isoformat(timespec="seconds"), "resolution": payload["resolution"], "seconds": str(payload["seconds"]), "job_id": job.get("job_id", "")}
            if res.get("status") == "pending":
                costlog.append_log(p, {**row, "cost": price, "result": "pending", "cost_source": "estimated"})
                return {"kind": kind, "pending": True, "job_id": row["job_id"]}
            if res.get("status") == "failed":
                costlog.append_log(p, {**row, "cost": res.get("cost", 0), "result": "failed"})
                return {"kind": kind, "error": res.get("error", "extension failed"), "cost": res.get("cost", 0)}
            out = p / "clips" / f"{target}_clip_extend_a{attempt}.mp4"
            with self._logged_output(p, {**row, "cost": res["cost"]}):
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(res["bytes"])
            return {"kind": kind, "file": out.relative_to(p).as_posix(), "cost": res["cost"]}
        if kind == "image":
            refs = [inputs / r["path"] for r in payload.get("refs", [])]
            out = p / payload["out"]
            if out.exists():
                raise ServiceError(f"{payload['out']} exists; discard it first")
            res = self.ws.runner().image(payload["prompt"], [str(r) for r in refs], payload["aspect_ratio"], project_dir=p, grant=grant)
            log = {**log, "model": res["model"], "provider": res["provider"], "cost_source": res["cost_source"]}
            data = res["bytes"]
            out = out.with_suffix(".jpg" if data[:3] == b"\xff\xd8\xff" else ".png")
            with self._logged_output(p, {**log, "timestamp": datetime.now().isoformat(timespec="seconds"), "resolution": "2K", "cost": res["cost"]}):
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
            return {"kind": kind, "file": out.relative_to(p).as_posix(), "cost": res["cost"]}
        if kind == "clip":
            ff = str(inputs / payload["first_frame"]) if payload["first_frame"] else None
            req = {"prompt": payload["prompt"], "seconds": payload["seconds"], "resolution": payload["resolution"], "aspect_ratio": payload["aspect_ratio"],
                   "audio": payload["audio"], "first_frame": ff}
            res = self.ws.runner().video(req, project_dir=p, grant=grant)
            job = res.get("job") or {}
            row = {**log, "model": res.get("model") or model, "provider": res.get("provider") or log["provider"], "cost_source": res.get("cost_source", ""),
                   "timestamp": datetime.now().isoformat(timespec="seconds"), "resolution": payload["resolution"], "seconds": str(payload["seconds"]),
                   "job_id": job.get("job_id", "")}
            if res["status"] == "pending":
                costlog.append_log(p, {**row, "cost": price, "result": "pending", "cost_source": "estimated"})
                return {"kind": kind, "pending": True, "job_id": row["job_id"]}
            if res["status"] == "failed":
                costlog.append_log(p, {**row, "cost": res.get("cost", 0), "result": "failed"})
                return {"kind": kind, "error": res["error"], "cost": res.get("cost", 0)}
            out = p / "clips" / f"{target}_final_a{attempt}.mp4"
            with self._logged_output(p, {**row, "cost": res["cost"]}):
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(res["bytes"])
            return {"kind": kind, "file": out.relative_to(p).as_posix(), "cost": res["cost"]}
        return self._do_review(p, target, payload, model, log, grant, inputs)

    def _do_review(self, p, target, payload, model, log, grant, inputs):
        f = inputs / payload["file"]
        outdir = p / "checks" / f.stem
        outdir.mkdir(parents=True, exist_ok=True)
        if payload.get("review_type") == "character":
            raw = self.ws.runner().review(character_check.build_character_check_prompt(), [str(f)], {"max_tokens": 1500, "temperature": 0.2}, project_dir=p, grant=grant, allow_paid=self.ws.ai_settings()["settings"].get("allow_paid", False))
            review = {**character_check.parse_character_analysis(raw["text"]), "file": payload["file"], "model": raw["model"], "cost": raw["cost"], "when": datetime.now().isoformat(timespec="seconds")}
            log = {**log, "model": raw["model"], "provider": raw["provider"], "cost_source": raw["cost_source"]}
            with self._logged_output(p, {**log, "timestamp": datetime.now().isoformat(timespec="seconds"), "resolution": "", "cost": raw["cost"]}):
                project_mod.save_json(outdir, "character_review.json", review)
            return {"kind": "review", "review_type": "character", "review": review}
        if f.suffix == ".mp4":
            shot = payload["shot_spec"]
            if f.read_bytes()[:7] == b"FAKEMP4":
                frames = []
            else:
                frames = frames_mod.extract(f, outdir, 8, shot.get("seconds", 4))
            prompt = payload["review_prompt"]
            ff = shot.get("first_frame")
            frames = ([str(inputs / ff)] if ff else []) + frames
        else:
            prompt = payload["review_prompt"]
            frames = [str(inputs / r["path"]) for r in payload.get("refs", [])] + [str(f)]
        raw = self.ws.runner().review(prompt, frames, {"max_tokens": 3500, "temperature": 0.2}, project_dir=p, grant=grant, allow_paid=self.ws.ai_settings()["settings"].get("allow_paid", False))
        res = {**clip_checklist.parse_review(raw["text"]), "cost": raw["cost"]}
        log = {**log, "model": raw["model"], "provider": raw["provider"], "cost_source": raw["cost_source"]}
        review = {k: res[k] for k in ("verdict", "findings", "summary")}
        review.update({"target": target, "model": raw["model"], "cost": res.get("cost", 0), "when": datetime.now().isoformat(timespec="seconds"),
                       "advisory": "A human still approves. A vision model cannot judge the spoken language."})
        with self._logged_output(p, {**log, "timestamp": datetime.now().isoformat(timespec="seconds"), "resolution": "", "cost": res.get("cost", 0)}):
            project_mod.save_json(outdir, "review.json", review)
        return {"kind": "review", "review": review}

    def approve_shot(self, name, shot_id):
        p = self.ws.pdir(name)
        doc = self.ws._read(p, "shots.json")
        shot = next((s for s in doc["shots"] if s["id"] == shot_id), None) or (_ for _ in ()).throw(ServiceError("unknown shot"))
        done = [r for r in costlog.read_log(p) if r["shot"] == shot_id and r["stage"] == "final" and r["result"] == "completed"]
        if not done:
            raise ServiceError("no completed clip to approve")
        shot["final_ok"] = True
        shot["final_clip"] = f"clips/{shot_id}_final_a{done[-1]['attempt']}.mp4"
        project_mod.save_json(p, "shots.json", doc)
        return shot

    def _void_proposals(self, p, pred):
        items = self.ws._read(p, "proposals.json", [])
        for x in items:
            if x["status"] in ("pending", "approved") and pred(x):
                x["status"] = "rejected"
        if items:
            project_mod.save_json(p, "proposals.json", items)
