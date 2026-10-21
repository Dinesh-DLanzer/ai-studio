"""Pipeline domain: proposals, approvals, execution, batch generation and review logic."""
from contextlib import contextmanager
import json
import re
from datetime import datetime
from pathlib import Path
import shutil
import tempfile

from aistudio import activity, approvals, chat as chat_mod, costlog, editor as editor_mod, frames as frames_mod, gates, palette as palette_mod, project as project_mod, project_lock, roles as roles_mod
from aistudio.domain.costs import BudgetStale
from aistudio.domain import spec as spec_mod
from aistudio.domain.common import REVIEW_PRICE, ServiceError, _ident, _sha
from aistudio.providers import base as pbase
from aistudio import character_check, consent as consent_mod
from aistudio.vision import clip_checklist, image_checklist


MAX_VARIANTS = 4
AI_TOOLS = spec_mod.AI_TOOLS
ASPECTS = ("9:16", "16:9", "1:1", "4:5")


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
        """(price, model) of one image or clip exactly as its GenerationSpec charges now; inputs need not exist yet."""
        sp = spec_mod.resolve(self.ws, p, "image" if kind == "image" else "clip", target, loose=True)
        return sp.price, sp.model

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

    @staticmethod
    def _variant(options):
        v = (options or {}).get("variant")
        if v in (None, 0, ""):
            return None
        if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= MAX_VARIANTS:
            raise ServiceError(f"variant must be a whole number from 1 to {MAX_VARIANTS}")
        return v

    def _require_consent(self, p, kind, target):
        """Generation touching an asset marked real_person is refused without a human-recorded consent entry (propose AND execute)."""
        doc = self.ws._read(p, "images.json", {"images": []})
        if kind == "image":
            spec = next((i for i in doc["images"] if i.get("id") == target), {})
            ids = [target, *spec.get("refs", [])]
        else:
            shot = next((s for s in self.ws._read(p, "shots.json", {"shots": []})["shots"] if s["id"] == target), {})
            ids = [r.get("id") if isinstance(r, dict) else str(r) for r in shot.get("refs") or []]
            ids += [Path(shot[k]).stem for k in ("first_frame", "end_frame") if shot.get(k)]
        consent_mod.require_assets(p, doc, ids)

    def _require_source_consent(self, p, kind, target, options):
        """Editing, extending or restyling a real person's asset needs the same human-recorded consent, and consent is also bound to the file bytes:
        a file a human marked (consent.mark_real_person) stays covered when the real_person flag is cleared. motion_transfer and character_swap always
        need a recorded consent for the named subject."""
        files = [options["source"], *([options["reference"]] if options.get("reference") else [])]
        ids = {target}
        for f in files:
            stem = Path(str(f)).stem
            ids |= {stem, stem.split("_edit_a")[0], stem.split("_extended")[0], stem.split(".v")[0], stem.split("_final_a")[0]}
        consent_mod.require_assets(p, self.ws._read(p, "images.json", {"images": []}), sorted(ids))
        consent_mod.require_shas(p, [_sha(self._source_file(p, f, "source")) for f in files])
        if kind in ("motion_transfer", "character_swap"):
            subject = str(options.get("subject") or "").strip()
            if not subject:
                raise ServiceError(f"{kind} needs the person's name as 'subject' (their recorded consent is required)")
            consent_mod.require(p, subject)

    def _tool_payload(self, p, kind, target, options):
        """Payload, model, price of a paid AI clip tool: the source and reference are bound by path and bytes, with the prompt, parameters and provider."""
        source = self._source_file(p, options.get("source"), "clip")
        if options.get("reference"):
            ref = self._source_file(p, options["reference"], "reference")
        elif kind in ("motion_transfer", "character_swap"):
            raise ServiceError(f"{kind} needs a reference ({'a driving video' if kind == 'motion_transfer' else 'the new character image'})")
        else:
            ref = None
        prompt, params = str(options.get("prompt", "")), {}
        if kind in ("restyle", "replace") and not prompt.strip():
            raise ServiceError(f"{kind} needs a prompt describing the result")
        if kind == "upscale_ai":
            params["scale"] = options.get("scale", 2)
            if params["scale"] not in (2, 4) or isinstance(params["scale"], bool):
                raise ServiceError("scale must be 2 or 4")
        elif kind == "reframe_ai":
            params["aspect_ratio"] = options.get("aspect_ratio")
            if params["aspect_ratio"] not in ASPECTS:
                raise ServiceError(f"aspect_ratio must be one of {', '.join(ASPECTS)}")
        elif kind == "replace":
            params["target"] = options.get("target")
            if params["target"] not in ("object", "background"):
                raise ServiceError("target must be object or background")
        rel = source.relative_to(p.resolve()).as_posix()
        sp = spec_mod.resolve(self.ws, p, kind, target, {**options, "source": rel})
        payload = {"task": sp.task, "source": rel, "source_sha": _sha(source), "prompt": prompt, "params": params, "seconds": sp.seconds,
                   "resolution": sp.resolution, "provider": sp.provider}
        if ref:
            payload["refs"] = [{"path": ref.relative_to(p.resolve()).as_posix(), "sha": _sha(ref)}]
        if kind in ("motion_transfer", "character_swap"):
            payload["subject"] = str(options["subject"]).strip()
        return payload, sp.model, sp.price

    def _payload_and_price(self, name, kind, target, options=None):
        p = self.ws.pdir(name)
        options = options or {}
        _ident(target, "target")
        variant = self._variant(options)
        if kind in ("image", "clip"):
            self._require_consent(p, kind, target)
        elif kind in ("image_edit", "clip_extend", *AI_TOOLS) and options.get("source"):
            self._require_source_consent(p, kind, target, options)
        if kind == "image":
            sp = spec_mod.resolve(self.ws, p, "image", target)
            spec, refs, prompt = self.ws._image_spec(p, target)
            payload = {"prompt": prompt, "aspect_ratio": sp.aspect_ratio, "out": spec["out"], "provider": sp.provider,
                       "refs": [{"path": r.relative_to(p).as_posix(), "sha": _sha(r)} for r in refs]}
            if variant:      # only present when asked for, so the request digest of ordinary images is unchanged
                payload["variant"] = variant
            return payload, sp.model, sp.price
        if kind == "clip":
            sp = spec_mod.resolve(self.ws, p, "clip", target)
            shot = self._clip_spec(p, target)[0]
            ff, end = sp.start_frame or None, sp.end_frame or None
            prompt = shot["prompt"]
            if shot.get("direction") and not shot.get("camera") and sp.camera.get("prompt_text"):
                prompt = f"{prompt.rstrip()} {sp.camera['prompt_text']}".strip()      # structured direction becomes part of the approved prompt
            payload = {"prompt": prompt, "seconds": sp.seconds, "audio": sp.audio, "resolution": sp.resolution, "provider": sp.provider,
                       "aspect_ratio": sp.aspect_ratio, "first_frame": ff, "first_frame_sha": _sha(p / ff) if ff else ""}
            if sp.camera.get("native"):      # native camera parameters are bound into the approved request too
                payload["camera_native"] = sp.camera["native"]
            if end:      # only present when asked for, so the request digest of ordinary clips is unchanged
                payload.update(end_frame=end, end_frame_sha=_sha(p / end))
            root = p.resolve()
            found = [r for r in sp.refs if (p / r["path"]).resolve().is_relative_to(root) and (p / r["path"]).is_file()]      # contained in the project      # ids without a still on disk have nothing to send (the quote still counts them)
            if found:      # reference images are bound by path and bytes like the frames
                payload["refs"] = [{"path": r["path"], "sha": _sha(p / r["path"])} for r in found]
            if variant:
                payload["variant"] = variant
            return payload, sp.model, sp.price
        if kind in AI_TOOLS:
            return self._tool_payload(p, kind, target, options)
        if kind == "image_edit":
            source = self._source_file(p, options.get("source"), "still")
            sp = spec_mod.resolve(self.ws, p, "image_edit", target)
            return {"source": source.relative_to(p.resolve()).as_posix(), "source_sha": _sha(source), "prompt": str(options.get("prompt", "")),
                    "edit_mode": options.get("edit_mode", "inpaint_insertion"), "mask_mode": options.get("mask_mode", "MASK_MODE_BACKGROUND"),
                    "provider": sp.provider}, sp.model, sp.price
        if kind == "clip_extend":
            source = self._source_file(p, options.get("source"), "clip")
            sp = spec_mod.resolve(self.ws, p, "clip_extend", target, options)
            return {"source": source.relative_to(p.resolve()).as_posix(), "source_sha": _sha(source), "prompt": str(options.get("prompt", "")),
                    "seconds": sp.seconds, "aspect_ratio": "16:9", "resolution": sp.resolution, "provider": sp.provider}, sp.model, sp.price
        if kind == "review":
            if options.get("review_type") == "drift":      # PAID vision: only ever through this proposal (a human approves the exact price)
                f = self._review_file(p, target)
                doc = self.ws._read(p, "images.json", {"images": []})
                by = {i.get("id"): i for i in doc["images"]}
                shot = next((s for s in self.ws._read(p, "shots.json", {"shots": []})["shots"] if s["id"] == target), None)
                if shot:      # the shot's own references, else those of its first-frame still
                    ids = [r.get("id") if isinstance(r, dict) else str(r) for r in shot.get("refs") or []] or by.get(Path(shot.get("first_frame") or "").stem, {}).get("refs", [])
                else:
                    ids = by.get(target, {}).get("refs", [])
                chars = [c for c in dict.fromkeys(ids) if by.get(c, {}).get("kind") == "character" and (p / by[c]["out"]).is_file() and c != target]
                if not chars:
                    raise ServiceError(f"{target} has no character with a made reference image to compare against")
                e = self.ws._primary("vision", p)
                return {"review_type": "drift", "target": target, "file": f.resolve().relative_to(p.resolve()).as_posix(), "file_sha": _sha(f), "provider": e["provider"]["id"],
                        "characters": chars, "refs": [{"path": by[c]["out"], "sha": _sha(p / by[c]["out"])} for c in chars]}, e["model"], REVIEW_PRICE
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
        raise ServiceError("kind must be image, clip, image_edit, clip_extend, review or " + ", ".join(AI_TOOLS))

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
        if kind in ("image", "clip"):      # what the model can do, and what was adjusted, shown to the approver
            sp = spec_mod.resolve(self.ws, p, kind, target)
            summary.update(profile=sp.profile, warnings=sp.warnings, end_frame=sp.end_frame or None,
                           price_breakdown=self.ws.pricing().breakdown(sp.entry["card"], sp.seconds, sp.resolution, sp.audio, len(sp.refs)))
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
            stage = {"clip": "final", "image": "image", "image_edit": "image_edit", "clip_extend": "clip_extend", "review": "vision", **{k: k for k in AI_TOOLS}}[kind]
            variant = payload.get("variant")
            ledger = f"{target}.v{variant}" if variant else target      # a variant is its own ledger shot: own attempts, own cost rows, own discard match
            pending = [r for r in project_lock.read_reservations(p) if r.get("shot") == ledger and r.get("stage") == stage]
            attempted = {r["attempt"] for r in rows if r["shot"] == ledger and r["stage"] == stage}
            attempted.update(str(r["attempt"]) for r in pending)
            attempts = len(attempted)
            base = target.split(".v")[0]
            family = {(r["shot"], str(r["attempt"])) for r in rows if (r["shot"] == base or r["shot"].startswith(base + ".v")) and r["stage"] == stage}
            family.update((r.get("shot"), str(r["attempt"])) for r in project_lock.read_reservations(p)
                          if (r.get("shot") == base or str(r.get("shot", "")).startswith(base + ".v")) and r.get("stage") == stage)
            gate_attempts = max(attempts, len(family))      # variants of a shot count toward the shot's attempt cap (they cannot multiply it)
            try:
                gates.check_run(b, costlog.spent(p) + project_lock.reserved(p), price, gate_attempts if kind in ("clip", "image_edit", "clip_extend", *AI_TOOLS) else 0, override=override)
                request_digest = approvals.request_hash(kind, target, model, price, payload)
                grant = approvals.consume(p, pid, request_digest)
                project_lock.reserve(p, pid, price, actor=grant.actor, shot=ledger, stage=stage, attempt=attempts + 1,
                                     model=model, provider=payload.get("provider", ""))
            except (gates.GateError, approvals.ApprovalError) as e:
                raise ServiceError(str(e)) from None
            attempt = attempts + 1
            log = {"shot": ledger, "stage": stage, "model": model, "attempt": str(attempt), "job_id": "", "seconds": "", "provider": payload.get("provider", ""), "actor": grant.actor, "override": "yes" if override else "no", "quoted": price}
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
                logged = any(r.get("shot") == ledger and r.get("stage") == stage and r.get("attempt") == str(attempt)
                             for r in costlog.read_log(p))
                # Never erase evidence of possibly billed work if settlement failed.
                if logged or not approvals.get(p, pid).get("redeemed"):
                    project_lock.release(p, pid)

    @staticmethod
    def _snapshot_inputs(p, dest, payload):
        files = [(r["path"], r["sha"]) for r in payload.get("refs", [])]
        for path_key, hash_key in (("source", "source_sha"), ("file", "file_sha"), ("first_frame", "first_frame_sha"), ("end_frame", "end_frame_sha")):
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
            self._write_meta(p, out, payload, row, grant, res["cost"], kind, target, refs=[(payload["source"], payload["source_sha"])])
            return {"kind": kind, "file": out.relative_to(p).as_posix(), "cost": res["cost"]}
        if kind in AI_TOOLS:
            return self._execute_tool(p, kind, target, payload, price, attempt, log, grant, inputs)
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
            self._write_meta(p, out, payload, row, grant, res["cost"], kind, target, refs=[(payload["source"], payload["source_sha"])])
            return {"kind": kind, "file": out.relative_to(p).as_posix(), "cost": res["cost"]}
        if kind == "image":
            refs = [inputs / r["path"] for r in payload.get("refs", [])]
            out = p / payload["out"]
            if payload.get("variant"):
                out = out.with_name(f"{out.stem}.v{payload['variant']}{out.suffix}")
            if out.exists():
                raise ServiceError(f"{payload['out']} exists; discard it first")
            res = self.ws.runner().image(payload["prompt"], [str(r) for r in refs], payload["aspect_ratio"], project_dir=p, grant=grant,
                                         first=self._pin("image", p, payload, model), required={"task": "text_to_image", "refs": len(refs)})
            log = {**log, "model": res["model"], "provider": res["provider"], "cost_source": res["cost_source"]}
            data = res["bytes"]
            out = out.with_suffix(".jpg" if data[:3] == b"\xff\xd8\xff" else ".png")
            with self._logged_output(p, {**log, "timestamp": datetime.now().isoformat(timespec="seconds"), "resolution": "2K", "cost": res["cost"]}):
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
            self._write_meta(p, out, payload, {**log, "resolution": "2K"}, grant, res["cost"], kind, target, refs=[(r["path"], r["sha"]) for r in payload.get("refs", [])])
            return {"kind": kind, "file": out.relative_to(p).as_posix(), "cost": res["cost"]}
        if kind == "clip":
            ff = str(inputs / payload["first_frame"]) if payload["first_frame"] else None
            req = {"prompt": payload["prompt"], "seconds": payload["seconds"], "resolution": payload["resolution"], "aspect_ratio": payload["aspect_ratio"],
                   "audio": payload["audio"], "first_frame": ff}
            if payload.get("camera_native"):
                req["camera_native"] = payload["camera_native"]
            end = payload.get("end_frame")
            if end:
                req["last_frame"] = str(inputs / end)
            if payload.get("refs"):
                req["refs"] = [str(inputs / r["path"]) for r in payload["refs"]]
            res = self.ws.runner().video(req, project_dir=p, grant=grant, first=self._pin("video", p, payload, model), ref_count=len(spec_mod.resolve(self.ws, p, "clip", target).refs),
                                         required={"task": "image_to_video" if ff else "text_to_video", "end_frame": bool(end), "refs": len(payload.get("refs", []))})
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
            out = p / "clips" / f"{log['shot']}_final_a{attempt}.mp4"
            with self._logged_output(p, {**row, "cost": res["cost"]}):
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(res["bytes"])
            frames = [(payload[k], payload[k + "_sha"]) for k in ("first_frame", "end_frame") if payload.get(k)]
            self._write_meta(p, out, payload, row, grant, res["cost"], kind, target, refs=frames)
            return {"kind": kind, "file": out.relative_to(p).as_posix(), "cost": res["cost"]}
        return self._do_review(p, target, payload, model, log, grant, inputs)

    def _execute_tool(self, p, kind, target, payload, price, attempt, log, grant, inputs):
        ref = payload.get("refs") or []
        res = self.ws.runner().video_task(payload["task"], (inputs / payload["source"]).as_posix(), payload["prompt"], payload["params"],
                                          reference=(inputs / ref[0]["path"]).as_posix() if ref else None, seconds=payload["seconds"],
                                          resolution=payload["resolution"], project_dir=p, grant=grant)
        job = res.get("job") or {}
        row = {**log, "model": res.get("model") or log["model"], "provider": res.get("provider") or log["provider"], "cost_source": res.get("cost_source", ""),
               "timestamp": datetime.now().isoformat(timespec="seconds"), "resolution": payload["resolution"], "seconds": str(payload["seconds"]), "job_id": job.get("job_id", "")}
        if res.get("status") == "pending":
            costlog.append_log(p, {**row, "cost": price, "result": "pending", "cost_source": "estimated"})
            return {"kind": kind, "pending": True, "job_id": row["job_id"]}
        if res.get("status") == "failed":
            costlog.append_log(p, {**row, "cost": res.get("cost", 0), "result": "failed"})
            return {"kind": kind, "error": res.get("error", f"{kind} failed"), "cost": res.get("cost", 0)}
        src = p / payload["source"]
        base = re.sub(r"\.v\d+$", "", src.stem)
        k = 1
        while src.with_name(f"{base}.v{k}{src.suffix}").exists():
            k += 1
        out = src.with_name(f"{base}.v{k}{src.suffix}")      # a NEW version beside the source; the source is never touched
        with self._logged_output(p, {**row, "cost": res["cost"]}):
            out.write_bytes(res["bytes"])
        self._write_meta(p, out, payload, row, grant, res["cost"], kind, target, refs=[(payload["source"], payload["source_sha"]), *[(r["path"], r["sha"]) for r in ref]])
        return {"kind": kind, "file": out.relative_to(p).as_posix(), "cost": res["cost"]}

    @staticmethod
    def _write_meta(p, out, payload, row, grant, cost, kind, target, refs=()):
        """<file>.meta.json: everything needed to reproduce or remix this output. Written AFTER the cost-log row, and never allowed to fail the
        call: the paid result is already stored and accounted for. No seed is sent by any adapter yet, so it is recorded as 'not sent'."""
        skip = ("prompt", "provider", "refs", "out", "source", "source_sha", "first_frame_sha", "end_frame_sha")
        meta = {"kind": kind, "target": target, "prompt": payload.get("prompt", ""), "negative": payload.get("negative", ""), "model": row.get("model", ""), "provider": row.get("provider", ""),
                "seed": payload.get("seed", "not sent"), "refs": [{"id": Path(r).stem, "path": r, "sha": s} for r, s in refs],
                "params": {"kind": kind, "resolution": row.get("resolution", ""), **{k: v for k, v in payload.items() if k not in skip}},
                "spec_hash": grant.request_hash, "cost": cost, "created": datetime.now().isoformat(timespec="seconds"), "actor": grant.actor}
        try:
            project_mod.save_json(p, out.relative_to(p).as_posix() + ".meta.json", meta)
        except OSError:
            pass

    def remix(self, name, meta_rel, reveal_code=False):
        """A PROPOSAL pre-filled from an output's .meta.json (nothing is spent; a human approves it like any other). It re-prices today's request
        for the same kind and target, and says what differs from the recorded run. Providers do not promise identical results."""
        p = self.ws.pdir(name)
        meta_file = self._source_file(p, meta_rel, "metadata file")
        if not meta_file.name.endswith(".meta.json"):
            raise ServiceError("remix needs a .meta.json file")
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            kind, target = meta["kind"], meta["target"]
        except (ValueError, KeyError, TypeError):
            raise ServiceError("metadata file is unreadable") from None
        params, refs = meta.get("params") or {}, meta.get("refs") or []
        options = None
        if kind == "image_edit":
            options = {"source": refs[0]["path"], "prompt": meta.get("prompt", ""), "edit_mode": params.get("edit_mode"), "mask_mode": params.get("mask_mode")}
        elif kind == "clip_extend":
            options = {"source": refs[0]["path"], "prompt": meta.get("prompt", ""), "seconds": params.get("seconds", 5)}
        elif kind not in ("image", "clip"):
            raise ServiceError(f"cannot remix a {kind}")
        proposal = self.propose(name, kind, target, reveal_code=reveal_code, options=options)
        now, _, _ = self._payload_and_price(name, kind, target, options)
        changed = {"prompt": now.get("prompt", "") != meta.get("prompt", ""), "model": proposal["model"] != meta.get("model"),
                   "refs": sorted(r["sha"] for r in now.get("refs", [])) != sorted(r["sha"] for r in refs if "sha" in r) if kind == "image" else False}
        return {"proposal": proposal, "from": meta_rel, "changed": changed, "seed": meta.get("seed", "not sent"),
                "note": "Providers do not promise identical results, even with the same inputs."}

    def drift_check(self, name, target):
        """PROPOSE the paid identity-drift check of a shot or still (nothing is spent; a human approves the exact price)."""
        return self.propose(name, "review", target, options={"review_type": "drift"})

    def _pin(self, role, p, payload, model):
        """The approved provider/model as a chain entry, so the shot's own model runs first (the rest of the chain stays as fallback)."""
        return self.ws.runner().entry_for(role, payload.get("provider"), model, p)

    def _do_review(self, p, target, payload, model, log, grant, inputs):
        f = inputs / payload["file"]
        outdir = p / "checks" / f.stem
        outdir.mkdir(parents=True, exist_ok=True)
        if payload.get("review_type") == "drift":
            f_frames = frames_mod.extract(f, outdir, 3, 4) if f.suffix == ".mp4" and f.read_bytes()[:7] != b"FAKEMP4" else ([] if f.suffix == ".mp4" else [str(f)])
            raw = self.ws.runner().review(character_check.build_drift_prompt(payload["characters"]), [str(inputs / r["path"]) for r in payload["refs"]] + f_frames,
                                          {"max_tokens": 800, "temperature": 0.0}, project_dir=p, grant=grant, allow_paid=self.ws.ai_settings()["settings"].get("allow_paid", False))
            res = {**character_check.parse_drift(raw["text"], payload["characters"]), "target": target, "file": payload["file"], "model": raw["model"], "cost": raw["cost"],
                   "threshold": character_check.DRIFT_THRESHOLD, "when": datetime.now().isoformat(timespec="seconds")}
            log = {**log, "model": raw["model"], "provider": raw["provider"], "cost_source": raw["cost_source"]}
            with self._logged_output(p, {**log, "timestamp": datetime.now().isoformat(timespec="seconds"), "resolution": "", "cost": raw["cost"]}):
                project_mod.save_json(p / "checks", f"{target}.json", res)
            return {"kind": "review", "review_type": "drift", "review": res}
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

    def select_version(self, name, kind, target, k):
        """Pick version k of a still (stills/<id>.v<k>.<ext>) or a clip (clips/<id>.v<k>_final_a<n>.mp4). Every other version of that target goes
        through the normal discard path (moved to _discarded with its cost, restorable, never deleted). The shot (clip) or the asset (still)
        records selected_version, and the timeline / first-frame source now points at the chosen file. A human decision (not an agent route)."""
        p = self.ws.pdir(name)
        if kind not in ("image", "clip"):
            raise ServiceError("versions are for images and clips")
        k = self._variant({"variant": k}) or (_ for _ in ()).throw(ServiceError("choose a version number"))
        _ident(target, "target")
        d = "stills" if kind == "image" else "clips"
        pat = re.escape(target) + (r"\.v(\d+)\.[A-Za-z0-9]+" if kind == "image" else r"\.v(\d+)_final_a\d+\.mp4")
        found = {}
        for f in sorted((p / d).glob(f"{target}.v*")) if (p / d).is_dir() else []:
            m = re.fullmatch(pat, f.name)
            if m and f.is_file():
                found.setdefault(int(m.group(1)), f.relative_to(p).as_posix())
        if k not in found:
            raise ServiceError(f"version {k} of {target} does not exist (have: {', '.join(map(str, sorted(found))) or 'none'})")
        chosen = found[k]
        for n, rel in sorted(found.items()):
            if n != k:
                self.ws.discard(name, rel, f"version {n} not selected (kept v{k})")
        if kind == "clip":
            doc = self.ws._read(p, "shots.json")
            shot = next((s for s in doc["shots"] if s["id"] == target), None) or (_ for _ in ()).throw(ServiceError(f"unknown shot {target}"))
            shot.update(selected_version=k, final_clip=chosen)
            project_mod.save_json(p, "shots.json", doc)
        else:
            doc = self.ws._read(p, "images.json", {"images": []})
            img = next((i for i in doc["images"] if i["id"] == target), None) or (_ for _ in ()).throw(ServiceError(f"unknown image id {target}"))
            old = img["out"]
            img.update(selected_version=k, out=chosen)
            shots = self.ws._read(p, "shots.json", {"shots": []})
            for s in shots.get("shots", []):
                if s.get("first_frame") == old:
                    s["first_frame"] = chosen
            project_mod.save_json(p, "images.json", doc)
            project_mod.save_json(p, "shots.json", shots)
        self.ws._changed(name, "assets", "shots")
        return {"kind": kind, "target": target, "selected_version": k, "file": chosen, "discarded": sorted(n for n in found if n != k)}

    def approve_shot(self, name, shot_id):
        p = self.ws.pdir(name)
        doc = self.ws._read(p, "shots.json")
        shot = next((s for s in doc["shots"] if s["id"] == shot_id), None) or (_ for _ in ()).throw(ServiceError("unknown shot"))
        done = [r for r in costlog.read_log(p) if r["shot"] == shot_id and r["stage"] == "final" and r["result"] == "completed"]
        if not done and shot.get("selected_version") and shot.get("final_clip") and (p / shot["final_clip"]).is_file():
            shot["final_ok"] = True      # the human-selected variant (paid through its own cost-log rows) is the clip being approved
            project_mod.save_json(p, "shots.json", doc)
            return shot
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
