"""Project domain: project lifecycle, files, metadata, trash, asset/shot renaming, and discard/restore."""
import csv
from pathlib import Path
import re
import shutil

from aistudio import (
    approvals,
    chat as chat_mod,
    costlog,
    discard as discard_mod,
    imageconv,
    importzip as importzip_mod,
    languages as lang_mod,
    project as project_mod,
    trash as trash_mod,
)
from aistudio.domain.common import DOC_FILES, ID_RE, MD_MARK, REPO, ServiceError, _ident
from aistudio.schemas import load_doc


class ProjectDomain:
    def __init__(self, ws):
        self.ws = ws

    def list_projects(self):
        out = []
        for p in sorted((self.ws.root / "projects").iterdir()):
            if p.is_dir():
                b = self.ws._read(p, "budget.json", {})
                shots = self.ws._read(p, "shots.json", {"shots": []})["shots"]
                out.append({
                    "name": p.name,
                    "shots": len(shots),
                    "spent": round(costlog.spent(p), 3),
                    "estimate": b.get("estimate"),
                    "approved": bool(b.get("approved")),
                    "test": self.ws.is_test(p),
                    "assets": len(self.ws._read(p, "images.json", {"images": []}).get("images", [])),
                    "favorite": (p / "favorite.json").exists(),
                })
        return out

    def create_project(self, name, test_pipeline=False):
        try:
            p = project_mod.create_project(self.ws.root / "projects", _ident(name, "project name"))
        except (ValueError, FileExistsError) as e:
            raise ServiceError(str(e)) from None
        for fn in ("Story.md", "brief.md", "TODO.md"):  # start from the full guided templates
            t = REPO / "templates" / fn
            if t.exists():
                (p / fn).write_text(t.read_text(encoding="utf-8").replace("{{PROJECT}}", name), encoding="utf-8")
        if test_pipeline:
            project_mod.save_json(p, "sandbox.json", {"test_pipeline": True})
        return p.name

    def set_favorite(self, name, on):
        """Mark / unmark a project as a favorite."""
        p = self.ws.pdir(name)
        f = p / "favorite.json"
        if on:
            project_mod.save_json(p, "favorite.json", {"favorite": True})
        elif f.exists():
            f.unlink()
        return {"name": name, "favorite": bool(on)}

    def overview(self, name):
        p = self.ws.pdir(name)
        listing = lambda d: sorted(f.name for f in (p / d).glob("*") if f.is_file() and not f.name.startswith("."))
        test = self.ws.is_test(p)
        return {
            "name": name,
            "mode": "test" if test else "real",
            "test_pipeline": (p / "sandbox.json").exists(),
            "is_test": test,
            "shots": self.ws._read(p, "shots.json", {"shots": []}),
            "images": self.ws._read(p, "images.json", {"images": []}),
            "budget": self.ws._read(p, "budget.json", {}),
            "costs": costlog.split(p),
            "rates": self.ws.rates(),
            "discarded": discard_mod.list_discarded(p),
            "proposals": [approvals.get(p, x["id"]) for x in (self.ws._read(p, "proposals.json", []))][-50:],
            "files": {"stills": listing("stills"), "clips": listing("clips")},
            "reviews": {d.name: self.ws._read(d, "review.json") for d in sorted((p / "checks").glob("*")) if d.is_dir()} if (p / "checks").exists() else {},
        }

    def get_text(self, name, fn):
        if fn not in DOC_FILES:
            raise ServiceError("unknown document")
        if fn in ("brief.md", "TODO.md"):
            self._sync_md(name, fn)
        f = self.ws.pdir(name) / fn
        return f.read_text(encoding="utf-8") if f.exists() else ""

    def _sync_md(self, name, fn):
        """Write brief.md / TODO.md from brief.json / todos.json. A hand-written file is kept once as <name>.old.md first."""
        p = self.ws.pdir(name)
        f = p / fn
        old = f.read_text(encoding="utf-8") if f.exists() else ""
        if fn == "brief.md":
            text = chat_mod.render_brief_md(name, self.ws._read(p, "brief.json", {})) + MD_MARK
        else:
            text = self.ws._render_todo_md(name)
        if text == old:
            return
        plain = chat_mod.render_brief_md(name, self.ws._read(p, "brief.json", {})) if fn == "brief.md" else None
        if old.strip() and MD_MARK.strip() not in old and old != plain:
            keep = p / f"{f.stem}.old.md"
            if not keep.exists():
                keep.write_text(old, encoding="utf-8")
        f.write_text(text, encoding="utf-8")

    def _apply_brief_md(self, name, text):
        """Read '- **Label** (required): value' lines back into brief.json; an unanswered or empty line clears the field."""
        labels = {l: k for k, l, _, _ in chat_mod.BRIEF_FIELDS}
        vals, cur = {}, None
        for line in text.splitlines():
            m = re.match(r"^\s*[-*]\s*\*\*(.+?)\*\*(?:\s*\(required\))?\s*:\s*(.*)$", line)
            if m and m.group(1).strip() in labels:
                cur = labels[m.group(1).strip()]
                vals[cur] = m.group(2).strip()
            elif cur and line.strip() and not line.startswith("#") and not line.lstrip().startswith(("- **", "* **")) and not line.startswith("<!--"):
                vals[cur] += " " + line.strip()
        vals = {k: ("" if v.strip("_ ").lower() == "not answered yet" else v) for k, v in vals.items()}
        self.brief_put(name, {**vals, "_clear": True})

    def put_text(self, name, fn, text):
        if fn not in DOC_FILES:
            raise ServiceError("unknown document")
        if fn == "brief.md":
            self._apply_brief_md(name, text)
            self._sync_md(name, fn)
            return
        if fn == "TODO.md":
            self.ws._apply_todo_md(name, text)
            self._sync_md(name, fn)
            return
        if fn == "Story.md":
            project_mod.save_text(self.ws.pdir(name), fn, text)
        else:
            (self.ws.pdir(name) / fn).write_text(text, encoding="utf-8")
        if fn == "Story.md":
            self.ws._changed(name, "story")

    def add_file(self, name, rel, data, replace=False):
        """Upload a still: stills/<id>.<ext>."""
        p = self.ws.pdir(name)
        rp = Path(rel)
        if rp.parent.as_posix() != "stills" or rp.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif") or not ID_RE.match(rp.stem):
            raise ServiceError("uploads must go to stills/<id> with an image extension")
        try:
            data, ext = imageconv.normalise(data)
        except imageconv.ImageError as e:
            raise ServiceError(str(e)) from None
        existing = [p / "stills" / f"{rp.stem}{e}" for e in (".png", ".jpg", ".jpeg") if (p / "stills" / f"{rp.stem}{e}").exists()]
        if existing and not replace:
            raise ServiceError("an image with that id exists; use Replace (the old one is kept in Discarded)")
        for old in existing:
            self.discard(name, old.relative_to(p).as_posix(), "replaced by an upload")
        (p / "stills" / f"{rp.stem}.{ext}").write_bytes(data)
        self.ws._changed(name, "assets", "shots")

    def brief_get(self, name):
        p = self.ws.pdir(name)
        values = self.ws._read(p, "brief.json", {})
        return {"fields": [{"key": k, "label": l, "question": q, "required": r, "value": values.get(k, "")} for k, l, q, r in chat_mod.BRIEF_FIELDS], **chat_mod.progress(values)}

    def brief_put(self, name, updates):
        p = self.ws.pdir(name)
        updates = dict(updates or {})
        clear = bool(updates.pop("_clear", False))
        if isinstance(updates.get("language"), str):
            langs = lang_mod.split_languages(updates["language"])
            if len(langs) > 1:
                updates["language"] = langs[0]
                existing_extra = updates.get("extra_languages") or ""
                extra_set = list(dict.fromkeys(lang_mod.split_languages(existing_extra) + langs[1:]))
                updates["extra_languages"] = ", ".join(extra_set)
        clean = chat_mod.clean_updates(updates)
        emptied = [k for k, v in updates.items() if clear and k in chat_mod.FIELD_KEYS and not str(v).strip()]
        if "language" in clean:
            clean["language"] = lang_mod.canonical(clean["language"])
        if "extra_languages" in clean:
            clean["extra_languages"] = ", ".join(lang_mod.split_languages(clean["extra_languages"]))
        values = {**self.ws._read(p, "brief.json", {}), **clean}
        for k in emptied:
            values.pop(k, None)
        project_mod.save_json(p, "brief.json", load_doc("brief", values))
        self._sync_md(name, "brief.md")
        if "language" in clean and (p / "shots.json").exists():
            doc = self.ws._read(p, "shots.json", {"shots": []})
            doc["language"] = clean["language"]
            project_mod.save_json(p, "shots.json", doc)
        self.ws._changed(name, "brief", "shots", "story")
        return self.brief_get(name)

    def _rewrite_log(self, p, fn):
        rows = costlog.read_log(p)
        if not rows:
            return
        rows = [fn(dict(r)) for r in rows]
        with (p / "cost_log.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=costlog.LOG_COLS)
            w.writeheader()
            w.writerows(rows)

    def _retarget_discarded(self, p, old_prefix, new_prefix):
        recs = discard_mod.list_discarded(p)
        for r in recs:
            for k in ("file", "original"):
                d, _, base = r[k].rpartition("/")
                if base.startswith(old_prefix):
                    r[k] = f"{d}/{new_prefix}{base[len(old_prefix):]}" if d else new_prefix + base[len(old_prefix):]
        if recs:
            project_mod.save_json(p, "discarded.json", recs)

    def _plan_moves(self, p, dirs, old_prefix, new_prefix, pattern):
        moves = []
        for d in dirs:
            for f in sorted((p / d).glob(pattern)) if (p / d).is_dir() else []:
                if f.is_file() or f.is_dir():
                    moves.append((f, f.with_name(new_prefix + f.name[len(old_prefix):])))
        for _, dst in moves:
            if dst.exists():
                raise ServiceError(f"cannot rename: {dst.relative_to(p)} already exists")
        return moves

    def rename_project(self, name, new):
        _ident(new, "new project name")
        src = self.ws.pdir(name)
        dst = self.ws.root / "projects" / new
        if dst.exists():
            raise ServiceError(f"a project called {new} already exists")
        src.rename(dst)
        return new

    def import_project(self, zip_path, name=None, filename=""):
        """Create a project from a zip made by Export Project."""
        tmp_root = self.ws.root / "_import_tmp"
        tmp_root.mkdir(exist_ok=True)
        z, root, _ = importzip_mod.inspect(zip_path)
        z.close()
        name = (name or "").strip() or importzip_mod.derive_name(filename, root)
        if not importzip_mod.NAME_RE.match(name):
            raise importzip_mod.ImportError_(f"Invalid project name {name!r}: use letters, numbers, - and _ (up to 64).")
        if (self.ws.root / "projects" / name).exists():
            raise importzip_mod.ImportError_(f"A project called {name} already exists. Choose another name.")
        folder, notes = importzip_mod.extract_and_validate(zip_path, tmp_root)
        try:
            dst = importzip_mod.install(self.ws.root, folder, name)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        finally:
            try:
                tmp_root.rmdir()
            except OSError:
                pass
        return {"name": name, "notes": notes, "files": sum(1 for f in dst.rglob("*") if f.is_file())}

    def export_project(self, name, include_discarded=False):
        """Path of a temporary zip of the whole project."""
        return trash_mod.zip_project(self.ws.pdir(name), include_discarded)

    def delete_project(self, name, confirm):
        """Move the project to _trash (restorable)."""
        p = self.ws.pdir(name)
        real_name = p.name
        conf_str = str(confirm or "").strip().lower()
        if confirm != name and confirm != real_name and conf_str not in ("yes", "true", real_name.lower(), name.lower()):
            raise ServiceError(f"type the project name ('{real_name}') or 'yes' to confirm")
        try:
            return {"trash": trash_mod.move_to_trash(self.ws.root, real_name), "name": real_name}
        except trash_mod.TrashError as e:
            raise ServiceError(str(e)) from None

    def trash_list(self):
        return trash_mod.list_trash(self.ws.root)

    def trash_restore(self, tid, as_name=None):
        try:
            return {"name": trash_mod.restore(self.ws.root, tid, as_name)}
        except trash_mod.TrashError as e:
            raise ServiceError(str(e)) from None

    def rename_asset(self, name, old, new):
        p = self.ws.pdir(name)
        _ident(old, "asset id")
        _ident(new, "new asset id")
        imgs = self.ws._read(p, "images.json", {"images": []})
        by = {i["id"]: i for i in imgs["images"]}
        if old not in by:
            raise ServiceError(f"unknown asset {old}")
        if new in by:
            raise ServiceError(f"an asset called {new} already exists")
        moves = self._plan_moves(p, ("stills", "stills/_discarded"), old, new, f"{old}.*") + self._plan_moves(p, ("stills/_discarded",), old, new, f"{old}__*.*")
        moves += self._plan_moves(p, ("checks",), old, new, old)
        if list((p / "stills").glob(f"{new}.*")):
            raise ServiceError(f"stills/{new} already exists")
        for src, dst in moves:
            src.rename(dst)
        for i in imgs["images"]:
            if i["id"] == old:
                i["id"] = new
                i["out"] = re.sub(rf"(^|/){re.escape(old)}(\.[^./]+)$", rf"\g<1>{new}\g<2>", i["out"])
            i["refs"] = [new if r == old else r for r in i.get("refs", [])]
        project_mod.save_json(p, "images.json", imgs)
        shots = self.ws._read(p, "shots.json", {"shots": []})
        for s in shots["shots"]:
            if s.get("first_frame"):
                s["first_frame"] = re.sub(rf"(^|/){re.escape(old)}(\.[^./]+)$", rf"\g<1>{new}\g<2>", s["first_frame"])
        project_mod.save_json(p, "shots.json", shots)
        self._rewrite_log(p, lambda r: {**r, "shot": new} if (r["stage"] == "image" and r["shot"] == old) else r)
        self._retarget_discarded(p, old, new)
        self.ws._void_proposals(p, lambda x: x["kind"] == "image" and x["shot"] == old)
        self.ws._changed(name, "assets", "shots")
        return self.overview(name)

    def rename_shot(self, name, old, new):
        p = self.ws.pdir(name)
        _ident(old, "shot id")
        _ident(new, "new shot id")
        doc = self.ws._read(p, "shots.json", {"shots": []})
        ids = {s["id"] for s in doc["shots"]}
        if old not in ids:
            raise ServiceError(f"unknown shot {old}")
        if new in ids:
            raise ServiceError(f"a shot called {new} already exists")
        moves = self._plan_moves(p, ("clips", "clips/_discarded"), old + "_", new + "_", f"{old}_*")
        moves += self._plan_moves(p, ("checks",), old + "_", new + "_", f"{old}_*")
        for src, dst in moves:
            src.rename(dst)
        for s in doc["shots"]:
            if s["id"] == old:
                s["id"] = new
                if s.get("final_clip"):
                    s["final_clip"] = s["final_clip"].replace(f"clips/{old}_", f"clips/{new}_", 1)
        project_mod.save_json(p, "shots.json", doc)
        has_image = any(i["id"] == old for i in self.ws._read(p, "images.json", {"images": []})["images"])
        self._rewrite_log(p, lambda r: {**r, "shot": new} if (r["shot"] == old and (r["stage"] in ("final", "draft") or (r["stage"] == "vision" and not has_image))) else r)
        self._retarget_discarded(p, old + "_", new + "_")
        self.ws._void_proposals(p, lambda x: x["kind"] in ("clip", "review") and x["shot"] == old)
        self.ws._changed(name, "shots")
        return self.overview(name)

    def discard(self, name, rel, reason=""):
        p = self.ws.pdir(name)
        cost = 0.0
        stem = Path(rel).stem
        m = re.match(r"^(.+)_final_a(\d+)$", stem)
        if m:
            for r in costlog.read_log(p):
                if r["shot"] == m.group(1) and r["stage"] == "final" and r["attempt"] == m.group(2):
                    cost = float(r["cost"] or 0)
        else:
            for r in costlog.read_log(p):
                if r["stage"] == "image" and r["shot"] == stem:
                    cost = float(r["cost"] or 0)
        try:
            rec = discard_mod.discard_file(p, rel, reason, cost)
        except (ValueError, FileNotFoundError) as e:
            raise ServiceError(str(e)) from None
        self.ws._changed(name, "assets", "shots")
        return rec

    def restore(self, name, rel):
        try:
            out = discard_mod.restore_file(self.ws.pdir(name), rel).relative_to(self.ws.pdir(name)).as_posix()
        except (ValueError, FileNotFoundError, FileExistsError) as e:
            raise ServiceError(str(e)) from None
        self.ws._changed(name, "assets", "shots")
        return out
