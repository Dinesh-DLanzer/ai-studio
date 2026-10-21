"""Storyboard, shots, stills and timeline editor domain."""
import json
from pathlib import Path
import re
import shutil
import time
from copy import deepcopy

from aistudio import editor as editor_mod, languages as lang_mod, project as project_mod
from aistudio.schemas import load_doc
from aistudio.domain.common import ID_RE, ServiceError, _ident
from aistudio.storyboard import convert as story_mod


class StoryboardDomain:
    IMG_EXT = (".png", ".jpg", ".jpeg")

    def __init__(self, ws):
        self.ws = ws

    def convert_story(self, name, write=True, model="google/veo-3.1-lite", seconds=4, resolution="720p"):
        p = self.ws.pdir(name)
        try:
            story = story_mod.parse_story((p / "Story.md").read_text(encoding="utf-8"))
        except ValueError as e:
            raise ServiceError(str(e)) from None
        lang = lang_mod.canonical(self.ws._read(p, "brief.json", {}).get("language", "")) or None
        shots = story_mod.to_shots_doc(story, model, seconds, resolution, lang)
        old = self.ws._read(p, "images.json", {"style": "", "images": []})
        uploads = [i for i in old.get("images", []) if i.get("kind") == "other"]  # files the user uploaded stay in the asset list
        images = story_mod.to_images_doc(story, known_ids=[u["id"] for u in uploads])
        new_ids = {i["id"] for i in images["images"]}
        images["images"] += [u for u in uploads if u["id"] not in new_ids]
        if not images["style"]:
            images["style"] = old.get("style", "")
        errs = project_mod.validate_shots(shots) + project_mod.validate_images(images)
        if errs:
            raise ServiceError("; ".join(errs))
        if write:
            project_mod.save_json(p, "shots.json", shots)
            project_mod.save_json(p, "images.json", images)
            self.ws._changed(name, "story", "shots", "assets")
        return {"shots": shots, "images": images}

    def put_shots(self, name, doc):
        errs = project_mod.validate_shots(doc)
        if errs:
            raise ServiceError("; ".join(errs))
        project_mod.save_json(self.ws.pdir(name), "shots.json", load_doc("shots", doc))
        self.ws._changed(name, "shots")

    def put_images(self, name, doc):
        errs = project_mod.validate_images(doc)
        if errs:
            raise ServiceError("; ".join(errs))
        project_mod.save_json(self.ws.pdir(name), "images.json", load_doc("images", doc))
        self.ws._changed(name, "assets", "shots")

    @staticmethod
    def _slug(stem):
        x = re.sub(r"[^A-Za-z0-9_-]+", "_", stem.strip()).strip("_-").lower()[:60]
        return x or "asset"

    @staticmethod
    def _guess_kind(stem, used_as_first_frame):
        low = stem.lower()
        if used_as_first_frame or re.match(r"^s\d+[a-z]?([-_].*)?$", low):
            return "frame"
        if "logo" in low or "brand" in low or "icon" in low:
            return "other"
        if re.search(r"shop|store|stall|street|place|room|house|office|background|backdrop|set\b|location|interior|exterior", low):
            return "background"
        return "character"

    def unregistered_stills(self, name):
        """Images sitting in stills/ that the asset list does not know about (for example projects made before the list existed)."""
        p = self.ws.pdir(name)
        imgs = self.ws._read(p, "images.json", {"images": []})["images"]
        known_ids = {i["id"] for i in imgs}
        known_files = {Path(i["out"]).stem for i in imgs}
        ff = {Path(s["first_frame"]).name for s in self.ws._read(p, "shots.json", {"shots": []})["shots"] if s.get("first_frame")}
        out, taken = [], set(known_ids)
        for f in sorted((p / "stills").glob("*")):
            if not f.is_file() or f.suffix.lower() not in self.IMG_EXT or f.stem in known_ids or f.stem in known_files:
                continue
            base = self._slug(f.stem) if not ID_RE.match(f.stem) else f.stem
            cand, n = base, 2
            while cand in taken:
                cand, n = f"{base}_{n}", n + 1
            taken.add(cand)
            out.append({"file": f.name, "suggested_id": cand, "suggested_kind": self._guess_kind(f.stem, f.name in ff), "used_by_shots": f.name in ff})
        return out

    def import_stills(self, name, items):
        """Register existing images as assets. Each file is renamed to <id>.<ext> so the asset id and file name match (nothing is deleted)."""
        p = self.ws.pdir(name)
        doc = self.ws._read(p, "images.json", {"style": "", "images": []})
        ids = {i["id"] for i in doc["images"]}
        shots = self.ws._read(p, "shots.json", {"shots": []})
        plan = []
        for it in items or []:
            fname, aid, kind = str(it.get("file", "")), str(it.get("id", "")).strip(), it.get("kind")
            src = p / "stills" / fname
            if not fname or "/" in fname or "\\" in fname or not src.is_file() or src.suffix.lower() not in self.IMG_EXT:
                raise ServiceError(f"not an image in stills/: {fname}")
            _ident(aid, "asset id")
            if kind not in ("character", "background", "frame", "other"):
                raise ServiceError(f"{fname}: choose a category")
            if aid in ids or any(x[1] == aid for x in plan):
                raise ServiceError(f"an asset called {aid} already exists (or is listed twice)")
            ext = ".jpg" if src.suffix.lower() == ".jpeg" else src.suffix.lower()
            dst = p / "stills" / f"{aid}{ext}"
            if dst.exists() and not dst.samefile(src):  # samefile: a case-only rename on a case-insensitive disk is fine
                raise ServiceError(f"stills/{dst.name} already exists")
            plan.append((src, aid, kind, dst))
        for src, aid, kind, dst in plan:
            if dst.name != src.name:
                src.rename(dst)
            for s in shots["shots"]:
                if s.get("first_frame") and Path(s["first_frame"]).name == src.name:
                    s["first_frame"] = f"stills/{dst.name}"
            doc["images"].append({"id": aid, "kind": kind, "out": f"stills/{dst.name}", "prompt": f"{kind} {aid}", "refs": [],
                                  "aspect_ratio": "9:16" if kind == "frame" else "3:2"})
        project_mod.save_json(p, "images.json", doc)
        project_mod.save_json(p, "shots.json", shots)
        self.ws._changed(name, "assets", "shots")
        return self.ws.overview(name)

    def upload_image(self, name, aid=None, path=None, data=None, kind=None, replace=False, prompt="", real_person=False, subject=""):
        """Import an image file or base64 data into project assets (stills/<id>.<ext> and images.json)."""
        p = self.ws.pdir(name)
        if not path and not data:
            raise ServiceError("either path or data (base64) must be provided")

        if path:
            src = Path(path)
            if not src.is_absolute():
                src = (Path.cwd() / src).resolve()
            if not src.is_file():
                raise ServiceError(f"file not found: {path}")
            raw = src.read_bytes()
            if not aid:
                aid = self._slug(src.stem)
        elif isinstance(data, str):
            import base64
            clean_b64 = data.strip()
            if "," in clean_b64 and clean_b64.startswith("data:"):
                clean_b64 = clean_b64.split(",", 1)[1]
            try:
                raw = base64.b64decode(clean_b64)
            except Exception as e:
                raise ServiceError(f"invalid base64 image data: {e}")
        elif isinstance(data, (bytes, bytearray)):
            raw = bytes(data)
        else:
            raise ServiceError("invalid image data format")

        if not aid:
            aid = "asset"
        aid = self._slug(aid)
        _ident(aid, "asset id")

        if real_person:      # an upload of a real person is refused until a human has recorded consent (before any file is written)
            from aistudio import consent as consent_mod
            consent_mod.require(p, subject or aid)
        # Let add_file validate image format, normalize to PNG/JPEG, handle replace, and write to stills/<aid>.<ext>
        self.ws.add_file(name, f"stills/{aid}.png", raw, replace=bool(replace))

        # Check what file was actually written (e.g. .png, .jpg)
        written = None
        for ext in self.IMG_EXT:
            cand = p / "stills" / f"{aid}{ext}"
            if cand.exists():
                written = cand
                break
        rel_out = f"stills/{written.name}" if written else f"stills/{aid}.png"

        # Register or update in images.json
        doc = self.ws._read(p, "images.json", {"style": "", "images": []})
        shots = self.ws._read(p, "shots.json", {"shots": []})

        target_kind = kind
        if not target_kind:
            target_kind = self._guess_kind(aid, False)
        if target_kind not in ("character", "background", "frame", "other"):
            raise ServiceError("kind must be one of: character, background, frame, other")

        found = False
        for img in doc.get("images", []):
            if img.get("id") == aid:
                img["out"] = rel_out
                if kind:
                    img["kind"] = target_kind
                if prompt:
                    img["prompt"] = prompt
                if real_person:
                    img.update(real_person=True, subject=subject or aid)
                found = True
                break

        if not found:
            doc.setdefault("images", []).append({
                "id": aid,
                "kind": target_kind,
                "out": rel_out,
                "prompt": prompt or f"{target_kind} {aid}",
                "refs": [],
                "aspect_ratio": "9:16" if target_kind == "frame" else "3:2",
                **({"real_person": True, "subject": subject or aid} if real_person else {}),
            })

        if target_kind == "frame":
            for s in shots.get("shots", []):
                if s.get("id") == aid or (s.get("first_frame") and Path(s["first_frame"]).stem == aid):
                    s["first_frame"] = rel_out

        project_mod.save_json(p, "images.json", doc)
        project_mod.save_json(p, "shots.json", shots)
        self.ws._changed(name, "assets", "shots")
        return {"ok": True, "id": aid, "kind": target_kind, "file": rel_out, "registered": True}


    def edit_get(self, name):
        p = self.ws.pdir(name)
        stored, warning = self.ws._read(p, "edit.json"), None
        try:
            doc = editor_mod.clean(stored) if stored is not None else None
        except editor_mod.EditError as e:
            doc, warning = None, f"edit.json could not be used ({e}); showing the shots instead"
        saved = doc is not None
        if doc is None:
            doc = editor_mod.clean(editor_mod.default_edit(p, self.ws._read(p, "shots.json", {"shots": []})))
        missing = [i["id"] for i in doc["tracks"]["video"] + doc["tracks"]["audio"] if not (p / i["src"]).is_file()]
        return {"edit": doc, "saved": saved, "missing": missing, "warning": warning, "tools": editor_mod.tools(), "exports": editor_mod.list_exports(p)}

    def edit_put(self, name, doc):
        p = self.ws.pdir(name)
        raw_doc = deepcopy(doc)
        try:
            doc = editor_mod.clean(doc)
        except editor_mod.EditError as e:
            raise ServiceError(str(e)) from None
        def keep_extras(raw, normalized):
            if isinstance(raw, dict) and isinstance(normalized, dict):
                result = deepcopy(normalized)
                for key, value in raw.items():
                    result[key] = keep_extras(value, result[key]) if key in result else deepcopy(value)
                return result
            if isinstance(raw, list) and isinstance(normalized, list):
                return [keep_extras(value, normalized[i]) if i < len(normalized) else deepcopy(value)
                        for i, value in enumerate(raw)]
            return normalized
        normalized = doc
        to_save = load_doc("edit", keep_extras(raw_doc, normalized))
        project_mod.save_json(p, "edit.json", to_save)
        return doc

    def edit_export(self, name, progress=None):
        """Render the saved edit (or the default one) to exports/. Free: no model is called, so no budget gate."""
        import importlib
        import aistudio.editor as editor_mod
        importlib.reload(editor_mod)
        p = self.ws.pdir(name)
        doc = self.ws._read(p, "edit.json") or editor_mod.default_edit(p, self.ws._read(p, "shots.json", {"shots": []}))
        try:
            return {"file": editor_mod.render(p, doc, progress)}
        except editor_mod.EditError as e:
            raise ServiceError(str(e)) from None

    def exports(self, name):
        return editor_mod.list_exports(self.ws.pdir(name))

    def _edit_for_export(self, name):
        """The saved edit (or the default one) validated: the shared start of the NLE, caption and bundle exports.  Free: no model is called."""
        p = self.ws.pdir(name)
        doc = self.ws._read(p, "edit.json") or editor_mod.default_edit(p, self.ws._read(p, "shots.json", {"shots": []}))
        try:
            return p, editor_mod.clean(doc)
        except editor_mod.EditError as e:
            raise ServiceError(str(e)) from None

    def export_fcpxml(self, name):
        """The timeline as Final Cut Pro XML (text).  Free."""
        p, doc = self._edit_for_export(name)
        files, probes = editor_mod.media(p, doc)
        try:
            return editor_mod.export_fcpxml(doc, files, probes)
        except editor_mod.EditError as e:
            raise ServiceError(str(e)) from None

    def export_edl(self, name):
        """The timeline as a CMX 3600 EDL (text).  Free."""
        p, doc = self._edit_for_export(name)
        files, _ = editor_mod.media(p, doc)
        try:
            return editor_mod.export_edl(doc, files)
        except editor_mod.EditError as e:
            raise ServiceError(str(e)) from None

    def export_subtitles(self, name, fmt="srt"):
        """The subtitle cues as SubRip ('srt') or WebVTT ('vtt').  Free."""
        _, doc = self._edit_for_export(name)
        subs = doc["tracks"].get("subtitles") or {}
        if fmt not in ("srt", "vtt"):
            raise ServiceError("format must be srt or vtt")
        if not subs.get("cues"):
            raise ServiceError("there are no subtitle cues in this edit yet")
        return editor_mod.export_srt(subs) if fmt == "srt" else editor_mod.export_vtt(subs)

    def export_bundle(self, name):
        """The Canva / Google Vids zip: clips, sounds, captions, NLE timeline, summary and the newest preview.  Returns the temp zip path.
        Free: no model is called."""
        p, doc = self._edit_for_export(name)
        files, _ = editor_mod.media(p, doc)
        try:
            return editor_mod.export_bundle(p, doc, files)
        except editor_mod.EditError as e:
            raise ServiceError(str(e)) from None

    def add_audio(self, name, filename, data):
        """Save an uploaded music / sound file as audio/<slug>.<ext> (never overwrites: a number is added)."""
        p = self.ws.pdir(name)
        ext = Path(filename or "").suffix.lower()
        if ext not in editor_mod.AUDIO_SUFFIX:
            raise ServiceError("sound files must be " + ", ".join(editor_mod.AUDIO_SUFFIX))
        stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(filename).stem).strip("_")[:48] or "sound"
        (p / "audio").mkdir(exist_ok=True)
        dst, n = p / "audio" / f"{stem}{ext}", 2
        while dst.exists():
            dst = p / "audio" / f"{stem}_{n}{ext}"
            n += 1
        dst.write_bytes(data)
        info = editor_mod.probe(dst)
        if shutil.which("ffprobe") and not (info and info["audio"]):
            dst.rename(dst.with_name(dst.name + ".rejected"))
            raise ServiceError("that file could not be read as audio (kept as .rejected in the audio folder)")
        return {"src": f"audio/{dst.name}", "name": dst.stem, "duration": info["duration"] if info else None}

    def add_element(self, name, filename, data):
        """Save an uploaded image / element file as elements/<slug>.<ext> (never overwrites: a number is added)."""
        p = self.ws.pdir(name)
        ext = Path(filename or "").suffix.lower()
        if ext not in editor_mod.IMAGE_SUFFIX:
            raise ServiceError("element files must be " + ", ".join(editor_mod.IMAGE_SUFFIX))
        stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(filename).stem).strip("_")[:48] or "element"
        (p / "elements").mkdir(exist_ok=True)
        dst, n = p / "elements" / f"{stem}{ext}", 2
        while dst.exists():
            dst = p / "elements" / f"{stem}_{n}{ext}"
            n += 1
        dst.write_bytes(data)
        return {"src": f"elements/{dst.name}", "name": dst.stem}

    def list_elements(self, name):
        """List available overlay elements (uploaded elements + project stills)."""
        p = self.ws.pdir(name)
        items = []
        elem_dir = p / "elements"
        if elem_dir.is_dir():
            for f in sorted(elem_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if f.is_file() and f.suffix.lower() in editor_mod.IMAGE_SUFFIX and not f.name.startswith("."):
                    items.append({"src": f"elements/{f.name}", "name": f.stem, "kind": "uploaded"})
        stills_dir = p / "stills"
        if stills_dir.is_dir():
            for f in sorted(stills_dir.iterdir(), key=lambda x: x.name):
                if f.is_file() and f.suffix.lower() in editor_mod.IMAGE_SUFFIX and not f.name.startswith(".") and "_discarded" not in f.parts:
                    items.append({"src": f"stills/{f.name}", "name": f.stem, "kind": "still"})
        return items

    def edit_still(self, name, still_id, prompt, edit_mode="inpaint_insertion", mask_mode="MASK_MODE_BACKGROUND"):
        """Create an image-edit proposal; execution happens only after human approval."""
        p = self.ws.pdir(name)
        src_file = None
        for ext in self.IMG_EXT:
            cand = p / "stills" / f"{still_id}{ext}"
            if cand.is_file():
                src_file = cand
                break
        if not src_file:
            cand = p / still_id
            if cand.is_file():
                src_file = cand
        if not src_file:
            raise ServiceError(f"still not found: {still_id}")
        return self.ws.propose(name, "image_edit", still_id, options={
            "source": src_file.resolve().relative_to(p.resolve()).as_posix(), "prompt": str(prompt),
            "edit_mode": edit_mode, "mask_mode": mask_mode,
        })

    def extend_clip(self, name, clip_id, prompt, seconds=5):
        """Create a clip-extension proposal; execution happens only after human approval."""
        p = self.ws.pdir(name)
        src_file = None
        for ext in (".mp4", ".mov", ".webm"):
            cand = p / "clips" / f"{clip_id}{ext}"
            if cand.is_file():
                src_file = cand
                break
        if not src_file:
            cand = p / clip_id
            if cand.is_file():
                src_file = cand
        if not src_file:
            raise ServiceError(f"clip not found: {clip_id}")
        return self.ws.propose(name, "clip_extend", clip_id, options={
            "source": src_file.resolve().relative_to(p.resolve()).as_posix(), "prompt": str(prompt), "seconds": int(seconds),
        })
