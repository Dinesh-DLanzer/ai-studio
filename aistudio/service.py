"""Service layer: everything the web API, MCP server and CLI can do, in one place, so they all obey the same rules.

Rules enforced HERE (not in any UI):
  * every paid action (image, clip, review) is a PROPOSAL; it runs only after a human approves that exact proposal,
  * gates: approved budget, stop-loss, max attempts,
  * nothing is ever deleted (discard moves files),
  * there is no app-wide mode: every project is either a TEST project (simulated, free) or a real one; the files decide (see kind.py).
Standard library only.
"""
import csv
import hashlib
import json
import os
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from aistudio import aisettings, approvals, budget as budget_mod, chat as chat_mod, languages as lang_mod, verify as verify_mod, costlog, discard as discard_mod, frames as frames_mod, gates
from aistudio import editor as editor_mod, importzip as importzip_mod, kind as kind_mod, palette as palette_mod, trash as trash_mod
from aistudio import imageconv, migrate as migrate_mod, pricing as pricing_mod, project as project_mod, roles as roles_mod, secrets as secrets_mod
from aistudio.providers import base as pbase, config as pconf, openrouter
from aistudio.storyboard import convert as story_mod
from aistudio.vision import clip_checklist, image_checklist

REPO = Path(__file__).resolve().parent.parent
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
REVIEW_PRICE = 0.003


DOC_FILES = ("Story.md", "brief.md", "TODO.md")
MD_MARK = "\n<!-- kept in sync with the AI Studio visual editor -->\n"

class ServiceError(Exception):
    """A user-facing error (bad input, gate refused, missing file)."""


def _sha(path):
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""


def _ident(x, what="id"):
    if not isinstance(x, str) or not ID_RE.match(x):
        raise ServiceError(f"invalid {what}: {x!r}")
    return x


from aistudio.settings_api import SettingsMixin   # noqa: E402


class Workspace(SettingsMixin):
    VERIFY_DELAY = 1.5     # seconds to let a burst of edits settle before the background AI review
    def __init__(self, root, rates_path=None, transport=None, auto_verify=False, catalog_fetch=None, secrets=None):
        self.auto_verify = auto_verify            # the web server turns this on; library/tests keep it off (no surprise AI calls)
        self.catalog_fetch = catalog_fetch
        self._verify_lock, self._verify_running, self._catalog_cache = threading.Lock(), set(), None
        self.root = Path(root)
        (self.root / "projects").mkdir(parents=True, exist_ok=True)
        self.rates_path = Path(rates_path) if rates_path else (self.root / "rates.json" if (self.root / "rates.json").exists() else REPO / "rates.json")
        self.transport = transport  # tests inject a fake (v1-style) transport for the OpenRouter adapter
        self.settings_dir = self.root / "settings"
        self.secrets = secrets or secrets_mod.SecretStore()
        self._runner, self._health = None, roles_mod.Health()

    # ---------------------------------------------------------------- providers and roles (settings v2)
    def ensure_settings(self):
        if not (self.settings_dir / "roles.json").exists() or not (self.settings_dir / "providers.json").exists():
            migrate_mod.migrate(self.root, force_openrouter=self.transport is not None)
        if self.transport is not None and not getattr(self, "_or_defaults_done", False):
            # an injected (v1-style) transport speaks OpenRouter: make sure an OpenRouter provider and its default chains exist
            self._or_defaults_done = True
            provs = pconf.load_providers(self.settings_dir)
            if not any(x["type"] == "openrouter" for x in provs):
                new_provs, new_roles, _ = migrate_mod.plan(self.root, force_openrouter=True)
                doc = pconf.load_roles(self.settings_dir)
                for role, r in new_roles["roles"].items():
                    if not doc["roles"][role]["chain"]:
                        doc["roles"][role]["chain"] = r["chain"]
                provs = [x for x in new_provs if x["type"] == "openrouter"] + provs
                pconf.save_providers(self.settings_dir, provs)
                pconf.save_roles(self.settings_dir, doc, provs)

    def pricing(self):
        return pricing_mod.Pricing.load(self.rates_path, self.settings_dir)

    def runner(self):
        self.ensure_settings()
        if self._runner is None:
            t, shim = self.transport, None
            if t is not None:
                shim = lambda method, url, headers=None, body=None, raw=False, timeout=None: t(method, url[len(openrouter.API):] if url.startswith(openrouter.API) else url, body, raw)
            self._runner = roles_mod.RoleRunner(self.settings_dir, self.secrets, self.pricing(), transport=shim, fake_mode=self.forced_test, fake_for=self._fake_for,
                                                health=self._health, trust_transport=t is not None)
        self._runner.pricing = self.pricing()
        return self._runner

    def forced_test(self):
        """True when AISTUDIO_ALL_TEST=1 is set in the process environment: every project behaves as a test project.  Only for tests, CI and demos."""
        return os.environ.get("AISTUDIO_ALL_TEST", "").strip() == "1"

    def is_test(self, p):
        """A test project: its files say nothing real was generated (or it carries the Test pipeline marker).  Decides how it runs."""
        return self.forced_test() or (p is not None and kind_mod.is_test_project(p))

    def _chat_ready(self):
        """Can a real chat model be called right now?"""
        return any(e["problem"] is None and e["ptype"] != "fake" for e in self.runner().resolve("chat", None, configured=True))

    def _fake_for(self, role, p=None):
        """Real projects never touch the built-in test provider.  A test project simulates images, clips and reviews; its chat is the real AI
        when a chat model is ready, else the scripted interviewer."""
        if not self.is_test(p):
            return False
        return role != "chat" or not self._chat_ready()

    def _primary(self, role, p=None):
        """First callable entry of the role's chain (provider, model, price card) or a ServiceError that says what to do."""
        entries = self.runner().resolve(role, p)
        if not entries:
            raise ServiceError(f"No {pconf.ROLE_INFO[role]['title'].lower()} model is set. Open Settings, add a provider and choose a model for '{role}'.")
        ok = [e for e in entries if e["problem"] is None]
        if not ok:
            raise ServiceError(f"The {role} models cannot be used: " + "; ".join(f"{e['model']} ({e['problem']})" for e in entries) + ". Open Settings to fix the provider.")
        return ok[0]

    # ---------------------------------------------------------------- basics
    def rates(self):
        return json.loads(self.rates_path.read_text(encoding="utf-8"))

    def pdir(self, name):
        _ident(name, "project name")
        p = self.root / "projects" / name
        if not p.is_dir():
            raise ServiceError(f"no such project: {name}")
        return p

    def _read(self, pdir, fn, default=None):
        f = pdir / fn
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else default

    # ---------------------------------------------------------------- projects
    def list_projects(self):
        out = []
        for p in sorted((self.root / "projects").iterdir()):
            if p.is_dir():
                b = self._read(p, "budget.json", {})
                shots = self._read(p, "shots.json", {"shots": []})["shots"]
                out.append({"name": p.name, "shots": len(shots), "spent": round(costlog.spent(p), 3),
                            "estimate": b.get("estimate"), "approved": bool(b.get("approved")), "test": self.is_test(p),
                            "assets": len(self._read(p, "images.json", {"images": []}).get("images", [])), "favorite": (p / "favorite.json").exists()})
        return out

    def create_project(self, name, test_pipeline=False):
        try:
            p = project_mod.create_project(self.root / "projects", _ident(name, "project name"))
        except (ValueError, FileExistsError) as e:
            raise ServiceError(str(e)) from None
        for fn in ("Story.md", "brief.md", "TODO.md"):      # start from the full guided templates
            t = REPO / "templates" / fn
            if t.exists():
                (p / fn).write_text(t.read_text(encoding="utf-8").replace("{{PROJECT}}", name), encoding="utf-8")
        if test_pipeline:
            project_mod.save_json(p, "sandbox.json", {"test_pipeline": True})
        return p.name

    def set_favorite(self, name, on):
        """Mark / unmark a project as a favorite (a small favorite.json inside the project, so it travels with renames, exports and imports)."""
        p = self.pdir(name)
        f = p / "favorite.json"
        if on:
            project_mod.save_json(p, "favorite.json", {"favorite": True})
        elif f.exists():
            f.unlink()
        return {"name": name, "favorite": bool(on)}

    def overview(self, name):
        p = self.pdir(name)
        listing = lambda d: sorted(f.name for f in (p / d).glob("*") if f.is_file() and not f.name.startswith("."))   # .DS_Store etc. are not assets
        test = self.is_test(p)
        return {"name": name, "mode": "test" if test else "real", "test_pipeline": (p / "sandbox.json").exists(), "is_test": test,
                "shots": self._read(p, "shots.json", {"shots": []}), "images": self._read(p, "images.json", {"images": []}),
                "budget": self._read(p, "budget.json", {}), "costs": costlog.split(p), "rates": self.rates(),
                "discarded": discard_mod.list_discarded(p),
                "proposals": [approvals.get(p, x["id"]) for x in (self._read(p, "proposals.json", []))][-50:],
                "files": {"stills": listing("stills"), "clips": listing("clips")},
                "reviews": {d.name: self._read(d, "review.json") for d in sorted((p / "checks").glob("*")) if d.is_dir()} if (p / "checks").exists() else {}}

    # ---------------------------------------------------------------- story and files
    def get_text(self, name, fn):
        if fn not in DOC_FILES:
            raise ServiceError("unknown document")
        if fn in ("brief.md", "TODO.md"):               # derived from the structured data so the file can never disagree with the UI
            self._sync_md(name, fn)
        f = self.pdir(name) / fn
        return f.read_text(encoding="utf-8") if f.exists() else ""

    def _sync_md(self, name, fn):
        """Write brief.md / TODO.md from brief.json / todos.json. A hand-written file is kept once as <name>.old.md first."""
        p = self.pdir(name)
        f = p / fn
        old = f.read_text(encoding="utf-8") if f.exists() else ""
        if fn == "brief.md":
            text = chat_mod.render_brief_md(name, self._read(p, "brief.json", {})) + MD_MARK
        else:
            text = self._render_todo_md(name)
        if text == old:
            return
        plain = chat_mod.render_brief_md(name, self._read(p, "brief.json", {})) if fn == "brief.md" else None
        if old.strip() and MD_MARK.strip() not in old and old != plain:
            keep = p / f"{f.stem}.old.md"
            if not keep.exists():
                keep.write_text(old, encoding="utf-8")
        f.write_text(text, encoding="utf-8")

    def _render_todo_md(self, name):
        t = self.todos(name)
        lines = [f"# {name}: to-do list", "", "## Progress (updates by itself)"]
        for a in t["auto"]:
            lines.append(f"- [{'x' if a['done'] else ' '}] {a['title']}" + (f" ({a['progress']})" if a["progress"] else ""))
        lines += ["", "## My tasks (edit freely: tick, add or delete lines)"]
        lines += [f"- [{'x' if m['done'] else ' '}] {m['title']}" for m in t["manual"]]
        return "\n".join(lines) + "\n" + MD_MARK

    def _apply_todo_md(self, name, text):
        """Read the 'My tasks' checkboxes back into todos.json (auto progress lines are derived and ignored)."""
        p = self.pdir(name)
        auto = {a["title"] for a in self.todos(name)["auto"]}
        old = self._todo_store(p)
        by_title = {x["title"]: x for x in old}
        out, seen = [], set()
        in_mine = "## My tasks" not in text                     # a file without the section: take every checkbox that is not a progress line
        for line in text.splitlines():
            if line.startswith("## "):
                in_mine = line.startswith("## My tasks")
                continue
            m = re.match(r"^\s*[-*]\s*\[([ xX])\]\s*(.+?)\s*$", line)
            if not m or not in_mine:
                continue
            title = m.group(2)[:120]
            if title in auto or any(title.startswith(a + " (") for a in auto) or title in seen:
                continue
            seen.add(title)
            prev = by_title.get(title)
            out.append({"id": prev["id"] if prev else "t" + hashlib.sha1((title + str(len(out))).encode()).hexdigest()[:8], "title": title, "done": m.group(1) != " "})
        project_mod.save_json(p, "todos.json", out)
        self._changed(name, "todos")

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
            self._apply_todo_md(name, text)
            self._sync_md(name, fn)
            return
        (self.pdir(name) / fn).write_text(text, encoding="utf-8")
        if fn == "Story.md":
            self._changed(name, "story")

    def convert_story(self, name, write=True, model="google/veo-3.1-lite", seconds=4, resolution="720p"):
        p = self.pdir(name)
        try:
            story = story_mod.parse_story((p / "Story.md").read_text(encoding="utf-8"))
        except ValueError as e:
            raise ServiceError(str(e)) from None
        lang = lang_mod.canonical(self._read(p, "brief.json", {}).get("language", "")) or None
        shots = story_mod.to_shots_doc(story, model, seconds, resolution, lang)
        old = self._read(p, "images.json", {"style": "", "images": []})
        uploads = [i for i in old.get("images", []) if i.get("kind") == "other"]          # files the user uploaded stay in the asset list
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
            self._changed(name, "story", "shots", "assets")
        return {"shots": shots, "images": images}

    def put_shots(self, name, doc):
        errs = project_mod.validate_shots(doc)
        if errs:
            raise ServiceError("; ".join(errs))
        project_mod.save_json(self.pdir(name), "shots.json", doc)
        self._changed(name, "shots")

    def put_images(self, name, doc):
        errs = project_mod.validate_images(doc)
        if errs:
            raise ServiceError("; ".join(errs))
        project_mod.save_json(self.pdir(name), "images.json", doc)
        self._changed(name, "assets", "shots")

    def add_file(self, name, rel, data, replace=False):
        """Upload a still: stills/<id>.<ext>. Accepts PNG, JPEG, WebP, GIF, BMP, TIFF and HEIC (by content, not filename); everything
        that is not already PNG/JPEG is converted to PNG. With replace=True an existing image of that id is moved to stills/_discarded first."""
        p = self.pdir(name)
        rp = Path(rel)
        if rp.parent.as_posix() != "stills" or rp.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif") \
                or not ID_RE.match(rp.stem):
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
        self._changed(name, "assets", "shots")

    # ---------------------------------------------------------------- brief, todos, producer chat
    def brief_get(self, name):
        p = self.pdir(name)
        values = self._read(p, "brief.json", {})
        return {"fields": [{"key": k, "label": l, "question": q, "required": r, "value": values.get(k, "")} for k, l, q, r in chat_mod.BRIEF_FIELDS],
                **chat_mod.progress(values)}

    def brief_put(self, name, updates):
        p = self.pdir(name)
        updates = dict(updates or {})
        clear = bool(updates.pop("_clear", False))
        if isinstance(updates.get("language"), str) and len(lang_mod.split_languages(updates["language"])) > 1:
            raise ServiceError("Choose one voice language only.")
        clean = chat_mod.clean_updates(updates)
        emptied = [k for k, v in updates.items() if clear and k in chat_mod.FIELD_KEYS and not str(v).strip()]
        if "language" in clean:
            clean["language"] = lang_mod.canonical(clean["language"])
        if "extra_languages" in clean:
            clean["extra_languages"] = ", ".join(lang_mod.split_languages(clean["extra_languages"]))
        values = {**self._read(p, "brief.json", {}), **clean}
        for k in emptied:
            values.pop(k, None)
        project_mod.save_json(p, "brief.json", values)
        self._sync_md(name, "brief.md")
        if "language" in clean and (p / "shots.json").exists():          # keep the project language in one place
            doc = self._read(p, "shots.json", {"shots": []})
            doc["language"] = clean["language"]
            project_mod.save_json(p, "shots.json", doc)
        self._changed(name, "brief", "shots", "story")
        return self.brief_get(name)

    def _todo_store(self, p):
        t = self._read(p, "todos.json")
        if t is None:
            t = [{"id": "lang", "title": "Native speaker checks every spoken line", "done": False},
                 {"id": "assets", "title": "Gather logo, colours and font for the editor", "done": False},
                 {"id": "edit", "title": "Edit: trim, on-screen text, end card, music, AI label", "done": False}]
            project_mod.save_json(p, "todos.json", t)
        return t

    def todos(self, name):
        p = self.pdir(name)
        shots = self._read(p, "shots.json", {"shots": []})["shots"]
        images = self._read(p, "images.json", {"images": []})["images"]
        b = self._read(p, "budget.json", {})
        bp = chat_mod.progress(self._read(p, "brief.json", {}))
        have = {f.rsplit(".", 1)[0] for f in (x.name for x in (p / "stills").glob("*") if x.is_file())}
        made = sum(1 for i in images if i["id"] in have)
        ok = sum(1 for s in shots if s.get("final_ok"))
        auto = [
            {"id": "brief", "title": "Answer the brief questions", "done": bp["complete"], "progress": f"{bp['required_done']}/{bp['required_total']}", "tab": "chat"},
            {"id": "story", "title": "Approve the storyboard (shots and images listed)", "done": bool(shots), "progress": f"{len(shots)} shots", "tab": "story"},
            {"id": "budget", "title": "Set and approve the budget", "done": bool(b.get("approved")), "progress": f"${b.get('estimate')}" if b.get("estimate") else "", "tab": "costs"},
            {"id": "images", "title": "Make the character, background and scene images", "done": bool(images) and made == len(images), "progress": f"{made}/{len(images)}", "tab": "assets"},
            {"id": "clips", "title": "Generate and approve each clip, one at a time", "done": bool(shots) and ok == len(shots), "progress": f"{ok}/{len(shots)}", "tab": "shots"},
        ]
        return {"auto": auto, "manual": self._todo_store(p)}

    def todo_add(self, name, title):
        p = self.pdir(name)
        title = str(title).strip()[:120]
        if not title:
            raise ServiceError("empty task")
        t = self._todo_store(p)
        t.append({"id": "t" + hashlib.sha1((title + str(len(t))).encode()).hexdigest()[:8], "title": title, "done": False})
        project_mod.save_json(p, "todos.json", t)
        self._changed(name, "todos")
        self._sync_md(name, "TODO.md")
        return self.todos(name)

    def todo_toggle(self, name, tid):
        p = self.pdir(name)
        t = self._todo_store(p)
        item = next((x for x in t if x["id"] == tid), None) or (_ for _ in ()).throw(ServiceError("unknown task"))
        item["done"] = not item["done"]
        project_mod.save_json(p, "todos.json", t)
        self._changed(name, "todos")
        self._sync_md(name, "TODO.md")
        return self.todos(name)

    def todo_remove(self, name, tid):
        p = self.pdir(name)
        project_mod.save_json(p, "todos.json", [x for x in self._todo_store(p) if x["id"] != tid])
        self._changed(name, "todos")
        self._sync_md(name, "TODO.md")
        return self.todos(name)

    def chat_history(self, name):
        p = self.pdir(name)
        msgs = [({**m, "text": "(This answer was in an unreadable format and is hidden. Please ask again.)"} if m.get("role") == "assistant" and chat_mod.unreadable(m.get("text")) else m)
                for m in self._read(p, "chat.json", [])]
        return {"messages": msgs, "pending_story": (p / "pending_story.md").exists(),
                "brief": self.brief_get(name), "test_pipeline": (p / "sandbox.json").exists(),
                "mode": "test" if self.is_test(p) else "real", "progress": self.production_progress(name)}

    # ---------------------------------------------------------------- production state (what the chat and its checklist know)
    def _production(self, p):
        """Facts read from the project's files: brief progress, story, budget, every asset (made or not), uploads with their colours, every shot."""
        brief = self._read(p, "brief.json", {})
        shots_doc = self._read(p, "shots.json", {"shots": []})
        imgs = self._read(p, "images.json", {"style": "", "images": []})
        budget = self._read(p, "budget.json", {})
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
        return {"brief": brief, "progress": chat_mod.progress(brief), "story": {"shots": len(shots), "pending": (p / "pending_story.md").exists(), "style": imgs.get("style", "")},
                "budget": {"estimate": budget.get("estimate"), "approved": bool(budget.get("approved"))}, "assets": assets, "uploads": uploads, "shots": shots,
                "spent": round(costlog.spent(p), 3)}

    def production_progress(self, name):
        """The production checklist for the chat page: groups with counts, and the ONE next action (always in this order: brief, storyboard, budget,
        characters, backgrounds, scene frames, clips, approval, export).  Nothing here spends money; the buttons open the usual price approval."""
        st = self._production(self.pdir(name))
        a, shots, pr = st["assets"], st["shots"], st["progress"]
        by = {k: [x for x in a if x["kind"] == k] for k in ("character", "background", "frame")}
        done = lambda xs: sum(1 for x in xs if x["made"])
        groups = [{"key": "brief", "label": "Brief", "done": pr["required_done"], "total": pr["required_total"]},
                  {"key": "story", "label": "Storyboard", "done": 1 if shots else 0, "total": 1},
                  {"key": "budget", "label": "Budget approved", "done": 1 if st["budget"]["approved"] else 0, "total": 1}]
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
        imgs = sorted((x for x in st["assets"] if not x["made"]), key=lambda x: order.get(x["kind"], 3))
        items = [{"kind": "image", "target": x["id"], "label": f"{x['kind']} image: {x['id']}"} for x in imgs]
        items += [{"kind": "clip", "target": x["id"], "label": f"video clip: {x['id']}"} for x in st["shots"] if not x["clip"]]
        return items

    def generate_all_plan(self, name):
        """The exact price of every remaining image and clip (nothing is created or spent).  The page shows this once; the human approves the whole run,
        and each item then goes through the normal propose / approve / execute steps one after the other, stopping at the first problem."""
        p = self.pdir(name)
        queue = self.production_progress(name)["queue"]
        if not queue:
            raise ServiceError("nothing is left to generate (or the budget is not approved yet)")
        img_price = vid_price = None
        items = []
        for it in queue:
            if it["kind"] == "image":
                if img_price is None:
                    e = self._primary("image", p)
                    img_price = self.pricing().image_price(e["card"])
                    if img_price is None:
                        raise ServiceError(f"No price set for {e['model']}. Set it in Settings > Model Configuration before generating images.")
                    img_model = e["model"]
                items.append({**it, "price": img_price, "model": img_model})
            else:
                shot, doc, res, audio, _ = self._clip_spec_loose(p, it["target"])
                e = self._primary("video", p)
                price = self.runner().video_price(e, {"seconds": shot["seconds"], "resolution": res, "audio": audio})
                if price is None:
                    raise ServiceError(f"No price for {e['model']} at {res} ({shot['seconds']}s). Set it in Settings > Model Configuration.")
                items.append({**it, "price": price, "model": e["model"]})
        b = self._read(p, "budget.json", {})
        total = round(sum(x["price"] for x in items), 6)
        spent = round(costlog.spent(p), 6)
        return {"items": items, "total": total, "budget": {"estimate": b.get("estimate"), "stop_loss": b.get("stop_loss"), "spent": spent}}

    def _clip_spec_loose(self, p, shot_id):
        """Like _clip_spec but the first frame may not exist yet (it is made earlier in the same run)."""
        doc = self._read(p, "shots.json")
        shot = next((s for s in doc["shots"] if s["id"] == shot_id), None) or (_ for _ in ()).throw(ServiceError(f"unknown shot {shot_id}"))
        return shot, doc, shot.get("resolution") or doc.get("final_resolution", "720p"), shot.get("audio", doc.get("audio", False)), shot.get("first_frame")

    def _chat_state(self, p):
        """The compact JSON the chat model sees every turn, so it never has to guess (or invent) what has been done."""
        st = self._production(p)
        nxt = self.production_progress(p.name)["next"]
        return {"brief_so_far": {k: st["brief"].get(k, "") for k in chat_mod.FIELD_KEYS if st["brief"].get(k)}, "still_missing_required": st["progress"]["missing"],
                "storyboard": {"applied_shots": st["story"]["shots"], "draft_waiting_for_user": st["story"]["pending"], "shared_style": st["story"]["style"]},
                "budget": st["budget"], "assets": [{"id": x["id"], "kind": x["kind"], "made": x["made"]} for x in st["assets"]],
                "uploads": [{"id": u["id"], "colors": u["colors"]} for u in st["uploads"]],
                "shots": [{"id": x["id"], "clip_made": x["clip"], "approved": x["approved"]} for x in st["shots"]],
                "money_spent_usd": st["spent"], "next_step_for_the_user": nxt["label"] if nxt else ""}

    def chat_send(self, name, text, prefs=None, attachments=None):
        """One producer-chat turn. Free models only (or the scripted test interviewer in a test project); never spends money."""
        p = self.pdir(name)
        text = str(text or "").strip()
        if not text or len(text) > 3000:
            raise ServiceError("message must be 1 to 3000 characters")
        files = self._chat_attachments(p, attachments)
        history = self._read(p, "chat.json", [])
        brief = self._read(p, "brief.json", {})
        now = datetime.now().isoformat(timespec="seconds")
        res = {}
        test = self.is_test(p)
        fake_chat = self._fake_for("chat", p)
        if fake_chat:
            turn = chat_mod.scripted_turn(brief, history, text, files)
            model = "fake/scripted-interviewer"
        else:
            msgs = chat_mod.build_messages(history, text, self._chat_state(p), test, prefs, files)
            res = self._ai_call(name, "chat", msgs)
            turn, model = chat_mod.parse_turn(res["text"]), res["model"]
            if turn.get("malformed") or (turn["storyboard_md"] and not chat_mod.valid_storyboard(turn["storyboard_md"])):
                # the model answered in the wrong format: ask once more, with the rules repeated, before showing the user anything
                try:
                    res2 = self._ai_call(name, "chat", msgs + [{"role": "assistant", "content": (res["text"] or "")[:1500]}, {"role": "user", "content": chat_mod.RETRY_NOTE}])
                except ServiceError:
                    res2 = None                      # the second try is best effort: keep the first answer
                if res2:
                    turn2 = chat_mod.parse_turn(res2["text"])
                    if not turn2.get("malformed"):
                        turn, model = turn2, res2["model"]
                        res = {**res2, "cost": (res.get("cost") or 0) + (res2.get("cost") or 0)}
            if turn.get("malformed"):
                turn = {"reply": "Sorry, the chat model answered in a format I could not read. Please send your message again, or choose another chat model in Settings.",
                        "brief_updates": {}, "todos_add": [], "storyboard_md": None}
        if turn["brief_updates"]:
            self.brief_put(name, turn["brief_updates"])
        if files and not fake_chat:           # remember the logo and its colours in the brief, whatever the model did with them
            cur = str(self._read(p, "brief.json", {}).get("brand_assets", ""))
            add = "".join(f" Logo file: {f['id']}." + (f" Brand colours: {', '.join(f['colors'])}." if f["colors"] else "") for f in files if f"Logo file: {f['id']}" not in cur)
            if add:
                self.brief_put(name, {"brand_assets": (cur + add).strip()})
        for t in turn["todos_add"]:
            self.todo_add(name, t)
        reply = turn["reply"]
        applied = False
        if turn["storyboard_md"]:
            if chat_mod.valid_storyboard(turn["storyboard_md"]):
                (p / "pending_story.md").write_text(turn["storyboard_md"], encoding="utf-8")
                # brief -> story -> todo: once the brief is complete the storyboard becomes Story.md by itself, but only in a project that has
                # no shots yet (nothing to overwrite). Otherwise it waits as a draft for the user to apply.
                fresh = not self._read(p, "shots.json", {"shots": []})["shots"]
                if fresh and (prefs or {}).get("auto_storyboard", True) is not False:
                    try:
                        res2 = self.apply_pending_story(name)
                        applied = True
                        reply += f"\n\nI wrote Story.md ({len(res2['shots']['shots'])} shots) from your brief and updated your TODO list."
                    except ServiceError:
                        pass
            else:
                reply += "\n\n(I drafted a storyboard but it was not in the right format, so I did not save it. Ask me to try again.)"
        history += [{"role": "user", "text": text, "ts": now, **({"attachments": files} if files else {})},
                    {"role": "assistant", "text": reply, "ts": now, "model": model, **({"asked": turn["asked"]} if turn.get("asked") else {}),
                     **({"cost": res["cost"]} if not fake_chat and res.get("cost") else {})}]
        project_mod.save_json(p, "chat.json", history[-200:])
        return {**self.chat_history(name), "reply": reply, "applied": applied}

    def _chat_attachments(self, p, ids):
        """Images the user attached to a chat message: each must be an upload (category 'other') that exists.  Returns [{id, file, colors}]."""
        if not ids:
            return []
        if not isinstance(ids, list) or len(ids) > 4:
            raise ServiceError("attach up to 4 images per message")
        imgs = {i["id"]: i for i in self._read(p, "images.json", {"images": []})["images"]}
        out = []
        for aid in ids:
            i = imgs.get(aid)
            if not i or i.get("kind") != "other" or not (p / i["out"]).is_file():
                raise ServiceError(f"attached image not found: {aid}")
            out.append({"id": aid, "file": Path(i["out"]).name, "colors": palette_mod.dominant_colors(p / i["out"])})
        return out

    def pending_story(self, name):
        f = self.pdir(name) / "pending_story.md"
        return {"text": f.read_text(encoding="utf-8") if f.exists() else ""}

    def apply_pending_story(self, name):
        """Human action: turn the drafted storyboard into Story.md + shots.json + images.json (refuses if clips are already approved)."""
        p = self.pdir(name)
        f = p / "pending_story.md"
        if not f.exists():
            raise ServiceError("no drafted storyboard is waiting")
        if any(s.get("final_ok") for s in self._read(p, "shots.json", {"shots": []})["shots"]):
            raise ServiceError("this project already has approved clips; start a new project instead of replacing its storyboard")
        (p / "Story.md").write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
        res = self.convert_story(name)
        self._sync_md(name, "TODO.md")                 # the to-do list follows the story: new shots and images appear in its progress lines
        f.replace(p / "last_applied_story.md")        # replace, not rename: Windows refuses to rename onto an existing file
        return res

    def discard_pending_story(self, name):
        f = self.pdir(name) / "pending_story.md"
        if f.exists():
            f.replace(f.with_name("discarded_story.md"))
        return {"ok": True}


    # ---------------------------------------------------------------- AI models (chat + verify), cost and cap
    def _legacy_view(self):
        self.ensure_settings()
        doc, out = pconf.load_roles(self.settings_dir), aisettings.defaults()
        types = {p["id"]: p["type"] for p in pconf.load_providers(self.settings_dir)}
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
        self.ensure_settings()
        provs = pconf.load_providers(self.settings_dir)
        if not any(x["type"] == "openrouter" for x in provs):
            provs.insert(0, {"id": "openrouter", "type": "openrouter", "label": "OpenRouter", "base_url": "", "enabled": True})
            pconf.save_providers(self.settings_dir, provs)
        orid = next(x["id"] for x in provs if x["type"] == "openrouter")
        types = {x["id"]: x["type"] for x in provs}
        doc = pconf.load_roles(self.settings_dir)
        for r in aisettings.ROLES:
            keep = [c for c in doc["roles"][r]["chain"] if types.get(c["provider"]) != "openrouter"]
            doc["roles"][r]["chain"] = [{"provider": orid, "model": m} for m in new[r]["models"]] + keep
        for k in ("allow_paid", "ai_cap_usd", "auto_verify"):
            doc[k] = new[k]
        try:
            pconf.save_roles(self.settings_dir, doc, provs)
        except ValueError as e:
            raise ServiceError(str(e)) from None
        return self.ai_settings()

    def ai_catalog(self, refresh=False):
        """Text models from OpenRouter with prices (free first). Falls back to the built-in free list when offline."""
        now = time.time()
        if self._catalog_cache and not refresh and now - self._catalog_cache[0] < 600:
            return self._catalog_cache[1]
        rows, source = aisettings.static_catalog(), "built-in free list (could not reach OpenRouter)"
        try:
            if self.catalog_fetch:
                data = self.catalog_fetch()
            elif os.environ.get("AISTUDIO_NO_NETWORK") == "1":
                raise OSError("network disabled")
            else:
                import urllib.request
                data = json.load(urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=20))
            live = aisettings.parse_catalog(data)
            if live:
                rows, source = live, "live from OpenRouter"
        except Exception:
            pass
        out = {"models": rows[:500], "source": source}
        self._catalog_cache = (now, out)
        return out

    def ai_spent(self, name):
        return round(sum(float(r["cost"] or 0) for r in costlog.read_log(self.pdir(name)) if r["stage"] in ("chat", "verify")), 6)

    def _ai_call(self, name, role, messages):
        """The ONE place a text AI model is called (chat and verify roles). Free models cost $0. A paid or unpriced model needs the allow-paid
        switch, stops at the per-project cap, and every paid call is written to the cost log. The role's chain gives the fallback order."""
        p = self.pdir(name)
        cfg = self.ai_settings()["settings"]
        runner = self.runner()
        free = lambda e: bool(e["card"] and e["card"].get("kind") == "text" and e["card"].get("free"))
        paid = any(not free(e) for e in runner.resolve(role, p) if e["problem"] is None)
        if paid and self.ai_spent(name) >= cfg["ai_cap_usd"]:
            raise ServiceError(f"The AI spending cap for this project (${cfg['ai_cap_usd']:.2f}) is reached. Raise it in AI settings or switch to a free model.")
        allow = lambda e: (True, "") if free(e) or cfg["allow_paid"] else (False, "paid or unpriced model; turn on 'Allow paid models' (or set it as free) in Settings")
        try:
            res = runner.chat(role, messages, {"max_tokens": 3500, "temperature": 0.4}, project_dir=p, allow=allow)
        except (pbase.ProviderError, roles_mod.ChainError, ValueError) as e:
            raise ServiceError(f"The {role} model is unavailable: {e}") from None
        if res.get("cost"):
            attempt = 1 + len([r for r in costlog.read_log(p) if r["stage"] == role])
            costlog.append_log(p, {"timestamp": datetime.now().isoformat(timespec="seconds"), "shot": "_ai", "stage": role, "model": res["model"], "resolution": "",
                                   "seconds": "", "attempt": str(attempt), "job_id": "", "cost": res.get("cost", 0), "result": "completed",
                                   "provider": res.get("provider", ""), "cost_source": res.get("cost_source", "")})
        return res

    # ---------------------------------------------------------------- languages
    def languages(self):
        return [{"name": n, "tested": lang_mod.LANGUAGES[n][1], "script": bool(lang_mod.LANGUAGES[n][0])} for n in lang_mod.NAMES]

    # ---------------------------------------------------------------- verification (rules now, AI on change)
    def _verify_inputs(self, p, scope):
        brief = self._read(p, "brief.json", {})
        shots = self._read(p, "shots.json", {"shots": []})
        imgs = self._read(p, "images.json", {"images": []})
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
            art, rules = shots, verify_mod.lint_shots(shots, imgs, stills, lang)
        elif scope == "todos":
            art = self._todo_store(p)
            rules = verify_mod.lint_todos(art)
        else:
            raise ServiceError(f"unknown scope {scope}; use one of {', '.join(verify_mod.SCOPES)}")
        return art, rules, lang, brief, verify_mod.content_hash(art, lang)

    def _verify_ai(self, name, scope, art, brief, lang, rules):
        if self.is_test(self.pdir(name)):
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
        p = self.pdir(name)
        art, rules, lang, brief, h = self._verify_inputs(p, scope)
        store = self._read(p, "verify.json", {})
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
        p = self.pdir(name)
        store = self._read(p, "verify.json", {})
        out = {}
        for scope in verify_mod.SCOPES:
            art, rules, lang, brief, h = self._verify_inputs(p, scope)
            saved = store.get(scope) or {}
            ai = saved.get("ai") if saved.get("hash") == h else None
            rr = verify_mod.result(rules)
            findings = [{**x, "source": "rules"} for x in rr["findings"]] + [{**x, "source": "ai"} for x in (ai or {}).get("findings", [])]
            rank = {"ok": 0, "warn": 1, "fail": 2}
            status = max([rr["status"], (ai or {}).get("status", "ok")], key=lambda x: rank[x])
            out[scope] = {"status": status, "findings": findings, "rules": rr["status"], "ai": None if ai is None else {k: ai.get(k) for k in ("status", "model", "summary", "error")},
                          "ai_stale": bool(saved.get("ai")) and saved.get("hash") != h, "when": saved.get("when"),
                          "running": (name, scope) in self._verify_running}
        return out

    def _changed(self, name, *scopes):
        """Called after every modification. With auto_verify on (web server) the AI review runs in the background for changed content."""
        if not self.auto_verify:
            return
        for scope in scopes:
            key = (name, scope)
            with self._verify_lock:
                if key in self._verify_running:
                    continue
                self._verify_running.add(key)
            threading.Thread(target=self._verify_bg, args=(name, scope), daemon=True).start()

    def _verify_bg(self, name, scope):
        try:
            time.sleep(self.VERIFY_DELAY)        # let a burst of edits settle; the latest content is what gets reviewed
            p = self.pdir(name)
            if not self.ai_settings()["settings"]["auto_verify"]:
                return
            _, _, _, _, h = self._verify_inputs(p, scope)
            saved = (self._read(p, "verify.json", {}).get(scope) or {})
            if saved.get("hash") == h and saved.get("ai"):
                return
            self.verify_run(name, scope, ai=True)
        except Exception:
            pass                                 # verification must never break editing
        finally:
            with self._verify_lock:
                self._verify_running.discard((name, scope))

    def verify_now(self, name, scope):
        """User pressed Re-check: run rules + AI in the background right away (even if the content did not change)."""
        self.pdir(name)
        if scope not in verify_mod.SCOPES:
            raise ServiceError(f"unknown scope {scope}")
        key = (name, scope)
        with self._verify_lock:
            if key in self._verify_running:
                return {"running": True}
            self._verify_running.add(key)

        def work():
            try:
                self.verify_run(name, scope, ai=True)
            except Exception:
                pass
            finally:
                with self._verify_lock:
                    self._verify_running.discard(key)
        threading.Thread(target=work, daemon=True).start()
        return {"running": True}

    def wait_verify(self, timeout=10.0):
        t0 = time.time()
        while self._verify_running and time.time() - t0 < timeout:
            time.sleep(0.05)

    # ---------------------------------------------------------------- renames (project, asset, shot)
    def _rewrite_log(self, p, fn):
        rows = costlog.read_log(p)
        if not rows:
            return
        rows = [fn(dict(r)) for r in rows]
        with (p / "cost_log.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=costlog.LOG_COLS)
            w.writeheader()
            w.writerows(rows)

    def _void_proposals(self, p, pred):
        items = self._read(p, "proposals.json", [])
        for x in items:
            if x["status"] in ("pending", "approved") and pred(x):
                x["status"] = "rejected"
        if items:
            project_mod.save_json(p, "proposals.json", items)

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
        src = self.pdir(name)
        dst = self.root / "projects" / new
        if dst.exists():
            raise ServiceError(f"a project called {new} already exists")
        src.rename(dst)
        return new

    # ---------------------------------------------------------------- Review & Export, export / delete project
    def edit_get(self, name):
        p = self.pdir(name)
        stored, warning = self._read(p, "edit.json"), None
        try:
            doc = editor_mod.clean(stored) if stored is not None else None
        except editor_mod.EditError as e:
            doc, warning = None, f"edit.json could not be used ({e}); showing the shots instead"
        saved = doc is not None
        if doc is None:
            doc = editor_mod.clean(editor_mod.default_edit(p, self._read(p, "shots.json", {"shots": []})))
        missing = [i["id"] for i in doc["tracks"]["video"] + doc["tracks"]["audio"] if not (p / i["src"]).is_file()]
        return {"edit": doc, "saved": saved, "missing": missing, "warning": warning, "tools": editor_mod.tools(), "exports": editor_mod.list_exports(p)}

    def edit_put(self, name, doc):
        p = self.pdir(name)
        try:
            doc = editor_mod.clean(doc)
        except editor_mod.EditError as e:
            raise ServiceError(str(e)) from None
        tmp = p / "edit.json.tmp"
        tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p / "edit.json")
        return doc

    def edit_export(self, name, progress=None):
        """Render the saved edit (or the default one) to exports/.  Free: no model is called, so no budget gate."""
        p = self.pdir(name)
        doc = self._read(p, "edit.json") or editor_mod.default_edit(p, self._read(p, "shots.json", {"shots": []}))
        try:
            return {"file": editor_mod.render(p, doc, progress)}
        except editor_mod.EditError as e:
            raise ServiceError(str(e)) from None

    def exports(self, name):
        return editor_mod.list_exports(self.pdir(name))

    def add_audio(self, name, filename, data):
        """Save an uploaded music / sound file as audio/<slug>.<ext> (never overwrites: a number is added)."""
        p = self.pdir(name)
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

    def import_project(self, zip_path, name=None, filename=""):
        """Create a project from a zip made by Export Project.  Validated first; refuses (importzip.ImportError_) if anything is wrong.
        Approvals inside the zip are dropped. Returns {"name", "notes", "files"}."""
        tmp_root = self.root / "_import_tmp"
        tmp_root.mkdir(exist_ok=True)
        z, root, _ = importzip_mod.inspect(zip_path)
        z.close()
        name = (name or "").strip() or importzip_mod.derive_name(filename, root)
        if not importzip_mod.NAME_RE.match(name):
            raise importzip_mod.ImportError_(f"Invalid project name {name!r}: use letters, numbers, - and _ (up to 64).")
        if (self.root / "projects" / name).exists():
            raise importzip_mod.ImportError_(f"A project called {name} already exists. Choose another name.")
        folder, notes = importzip_mod.extract_and_validate(zip_path, tmp_root)
        try:
            dst = importzip_mod.install(self.root, folder, name)
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
        """Path of a temporary zip of the whole project; the caller deletes it after sending."""
        return trash_mod.zip_project(self.pdir(name), include_discarded)

    def delete_project(self, name, confirm):
        """Move the project to _trash (restorable).  The caller must send the exact project name as confirmation."""
        self.pdir(name)
        if confirm != name:
            raise ServiceError("type the project name exactly to confirm")
        try:
            return {"trash": trash_mod.move_to_trash(self.root, name)}
        except trash_mod.TrashError as e:
            raise ServiceError(str(e)) from None

    def trash_list(self):
        return trash_mod.list_trash(self.root)

    def trash_restore(self, tid, as_name=None):
        try:
            return {"name": trash_mod.restore(self.root, tid, as_name)}
        except trash_mod.TrashError as e:
            raise ServiceError(str(e)) from None

    def rename_asset(self, name, old, new):
        p = self.pdir(name)
        _ident(old, "asset id"); _ident(new, "new asset id")
        imgs = self._read(p, "images.json", {"images": []})
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
        shots = self._read(p, "shots.json", {"shots": []})
        for s in shots["shots"]:
            if s.get("first_frame"):
                s["first_frame"] = re.sub(rf"(^|/){re.escape(old)}(\.[^./]+)$", rf"\g<1>{new}\g<2>", s["first_frame"])
        project_mod.save_json(p, "shots.json", shots)
        self._rewrite_log(p, lambda r: {**r, "shot": new} if (r["stage"] == "image" and r["shot"] == old) else r)
        self._retarget_discarded(p, old, new)
        self._void_proposals(p, lambda x: x["kind"] == "image" and x["shot"] == old)
        self._changed(name, "assets", "shots")
        return self.overview(name)

    def rename_shot(self, name, old, new):
        p = self.pdir(name)
        _ident(old, "shot id"); _ident(new, "new shot id")
        doc = self._read(p, "shots.json", {"shots": []})
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
        has_image = any(i["id"] == old for i in self._read(p, "images.json", {"images": []})["images"])
        self._rewrite_log(p, lambda r: {**r, "shot": new} if (r["shot"] == old and (r["stage"] in ("final", "draft") or (r["stage"] == "vision" and not has_image))) else r)
        self._retarget_discarded(p, old + "_", new + "_")
        self._void_proposals(p, lambda x: x["kind"] in ("clip", "review") and x["shot"] == old)
        self._changed(name, "shots")
        return self.overview(name)


    # ---------------------------------------------------------------- import images that exist in stills/ but are not in the asset list
    IMG_EXT = (".png", ".jpg", ".jpeg")

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
        p = self.pdir(name)
        imgs = self._read(p, "images.json", {"images": []})["images"]
        known_ids = {i["id"] for i in imgs}
        known_files = {Path(i["out"]).stem for i in imgs}
        ff = {Path(s["first_frame"]).name for s in self._read(p, "shots.json", {"shots": []})["shots"] if s.get("first_frame")}
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
        p = self.pdir(name)
        doc = self._read(p, "images.json", {"style": "", "images": []})
        ids = {i["id"] for i in doc["images"]}
        shots = self._read(p, "shots.json", {"shots": []})
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
            if dst.exists() and not dst.samefile(src):          # samefile: a case-only rename on a case-insensitive disk is fine
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
        self._changed(name, "assets", "shots")
        return self.overview(name)

    # ---------------------------------------------------------------- budget
    def estimate(self, name, failure=0.2):
        p = self.pdir(name)
        shots, images = self._read(p, "shots.json"), self._read(p, "images.json", {"images": []})
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
        e = self._primary("video", p)
        if not e["card"] or e["card"].get("kind") != "video":
            raise ServiceError(f"No price set for {e['model']}. Set it in Settings > Model Configuration.")
        k = pricing_mod.key(e["provider"]["id"], e["model"])
        doc = {**shots, "shots": [{**s, "model": k} for s in shots["shots"]]}
        image_rate = 0.036
        try:
            ie = self._primary("image", p)
            image_rate = self.pricing().image_price(ie["card"]) or image_rate
        except ServiceError:
            pass
        return budget_mod.estimate(doc, images, {"models": {k: e["card"]["per_second"]}}, existing, failure, image_rate=image_rate)

    def approve_budget(self, name):
        """Human channel only (web UI / terminal). Not exposed through MCP."""
        p = self.pdir(name)
        b = self._read(p, "budget.json") or (_ for _ in ()).throw(ServiceError("run estimate first"))
        b["approved"] = True
        project_mod.save_json(p, "budget.json", b)
        return b

    # ---------------------------------------------------------------- proposals (every paid action)
    def _image_spec(self, p, img_id):
        imgs = self._read(p, "images.json", {"images": []})
        by = {i["id"]: i for i in imgs["images"]}
        if img_id not in by:
            raise ServiceError(f"unknown image id {img_id}")
        spec = by[img_id]
        refs = []
        for r in spec.get("refs", []):
            path = p / by[r]["out"] if r in by else p / r
            if not path.exists():
                raise ServiceError(f"reference not found: {r}")
            refs.append(path)
        prompt = (imgs.get("style", "") + " " + spec["prompt"]).strip()
        return spec, refs, prompt

    def _clip_spec(self, p, shot_id):
        doc = self._read(p, "shots.json")
        shot = next((s for s in doc["shots"] if s["id"] == shot_id), None) or (_ for _ in ()).throw(ServiceError(f"unknown shot {shot_id}"))
        res = shot.get("resolution") or doc.get("final_resolution", "720p")
        audio = shot.get("audio", doc.get("audio", False))
        ff = shot.get("first_frame")
        if ff and not (p / ff).exists():
            raise ServiceError(f"first frame missing: {ff}")
        return shot, doc, res, audio, ff

    def _payload_and_price(self, name, kind, target):
        p = self.pdir(name)
        _ident(target, "target")
        if kind == "image":
            spec, refs, prompt = self._image_spec(p, target)
            e = self._primary("image", p)
            price = self.pricing().image_price(e["card"])
            if price is None:
                raise ServiceError(f"No price set for {e['model']}. Set it in Settings > Model Configuration before generating images.")
            return {"prompt": prompt, "aspect_ratio": spec.get("aspect_ratio", "9:16"), "out": spec["out"], "provider": e["provider"]["id"],
                    "refs": [{"path": r.relative_to(p).as_posix(), "sha": _sha(r)} for r in refs]}, e["model"], price
        if kind == "clip":
            shot, doc, res, audio, ff = self._clip_spec(p, target)
            e = self._primary("video", p)
            req = {"seconds": shot["seconds"], "resolution": res, "audio": audio}
            price = self.runner().video_price(e, req)
            if price is None:
                raise ServiceError(f"No price for {e['model']} at {res} ({shot['seconds']}s). Set it in Settings > Model Configuration.")
            return {"prompt": shot["prompt"], "seconds": shot["seconds"], "audio": audio, "resolution": res, "provider": e["provider"]["id"],
                    "aspect_ratio": doc.get("aspect_ratio", "9:16"), "first_frame": ff, "first_frame_sha": _sha(p / ff) if ff else ""}, e["model"], price
        if kind == "review":
            f = self._review_file(p, target)
            e = self._primary("vision", p)
            return {"target": target, "file": f.relative_to(p).as_posix(), "file_sha": _sha(f), "provider": e["provider"]["id"]}, e["model"], REVIEW_PRICE
        raise ServiceError("kind must be image, clip or review")

    def _review_file(self, p, target):
        rows = [r for r in costlog.read_log(p) if r["shot"] == target and r["stage"] == "final" and r["result"] == "completed"]
        if rows:
            return p / "clips" / f"{target}_final_a{rows[-1]['attempt']}.mp4"
        for ext in (".png", ".jpg"):
            if (p / "stills" / f"{target}{ext}").exists():
                return p / "stills" / f"{target}{ext}"
        raise ServiceError(f"nothing to review for {target}")

    def propose(self, name, kind, target, reveal_code=False):
        """Nothing is spent. reveal_code=True ONLY from the human-facing channel (web UI / terminal)."""
        p = self.pdir(name)
        payload, model, price = self._payload_and_price(name, kind, target)
        summary = {"prompt": payload.get("prompt", "")[:400], "seconds": payload.get("seconds"), "audio": payload.get("audio"),
                   "first_frame": payload.get("first_frame"), "refs": [r["path"] for r in payload.get("refs", [])], "file": payload.get("file"), "provider": payload.get("provider")}
        return approvals.propose(p, kind, target, model, price, payload, reveal_code=reveal_code, summary=summary)

    def approve_human(self, name, pid):
        """HUMAN channel only (web UI / terminal). Never expose through MCP."""
        try:
            return approvals.approve_human(self.pdir(name), pid)
        except approvals.ApprovalError as e:
            raise ServiceError(str(e)) from None

    def proposal_status(self, name, pid):
        try:
            return approvals.get(self.pdir(name), pid)
        except approvals.ApprovalError as e:
            raise ServiceError(str(e)) from None

    def approve(self, name, pid, code):
        try:
            return approvals.approve(self.pdir(name), pid, code)
        except approvals.ApprovalError as e:
            raise ServiceError(str(e)) from None

    def reject(self, name, pid):
        try:
            approvals.reject(self.pdir(name), pid)
        except approvals.ApprovalError as e:
            raise ServiceError(str(e)) from None

    # ---------------------------------------------------------------- execution (only with an approved proposal)
    def execute(self, name, pid, override=False):
        p = self.pdir(name)
        try:
            prop = approvals.get(p, pid)
        except approvals.ApprovalError as e:
            raise ServiceError(str(e)) from None
        kind, target = prop["kind"], prop["shot"]
        payload, model, price = self._payload_and_price(name, kind, target)
        b = self._read(p, "budget.json", {})
        rows = costlog.read_log(p)
        stage = {"clip": "final", "image": "image", "review": "vision"}[kind]
        attempts = len([r for r in rows if r["shot"] == target and r["stage"] == stage])
        try:
            gates.check_run(b, costlog.spent(p), price, attempts if kind == "clip" else 0, override=override)
            approvals.consume(p, pid, kind, target, model, price, payload)
        except (gates.GateError, approvals.ApprovalError) as e:
            raise ServiceError(str(e)) from None
        attempt = attempts + 1
        log = {"shot": target, "stage": stage, "model": model, "attempt": str(attempt), "job_id": "", "seconds": "", "provider": payload.get("provider", "")}
        try:
            return self._execute_kind(p, kind, target, payload, model, price, attempt, log)
        except roles_mod.NeedsNewApproval as e:
            raise ServiceError(f"{e} Nothing was spent. Propose again to approve the new price.") from None
        except (roles_mod.ChainError, pbase.ProviderError) as e:
            raise ServiceError(str(e)) from None

    def _execute_kind(self, p, kind, target, payload, model, price, attempt, log):
        if kind == "image":
            _, refs, _ = self._image_spec(p, target)
            out = p / payload["out"]
            if out.exists():
                raise ServiceError(f"{payload['out']} exists; discard it first")
            res = self.runner().image(payload["prompt"], [str(r) for r in refs], payload["aspect_ratio"], project_dir=p, approved_price=price)
            log = {**log, "model": res["model"], "provider": res["provider"], "cost_source": res["cost_source"]}
            data = res["bytes"]
            out = out.with_suffix(".jpg" if data[:3] == b"\xff\xd8\xff" else ".png")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            costlog.append_log(p, {**log, "timestamp": datetime.now().isoformat(timespec="seconds"), "resolution": "2K", "cost": res["cost"], "result": "completed"})
            return {"kind": kind, "file": out.relative_to(p).as_posix(), "cost": res["cost"]}
        if kind == "clip":
            ff = str(p / payload["first_frame"]) if payload["first_frame"] else None
            req = {"prompt": payload["prompt"], "seconds": payload["seconds"], "resolution": payload["resolution"], "aspect_ratio": payload["aspect_ratio"],
                   "audio": payload["audio"], "first_frame": ff}
            res = self.runner().video(req, project_dir=p, approved_price=price)
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
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(res["bytes"])
            costlog.append_log(p, {**row, "cost": res["cost"], "result": "completed"})
            return {"kind": kind, "file": out.relative_to(p).as_posix(), "cost": res["cost"]}
        return self._do_review(p, target, payload, model, log)

    def _do_review(self, p, target, payload, model, log):
        f = p / payload["file"]
        outdir = p / "checks" / f.stem
        outdir.mkdir(parents=True, exist_ok=True)
        if f.suffix == ".mp4":
            doc = self._read(p, "shots.json", {"shots": []})
            shot = next((s for s in doc["shots"] if s["id"] == target), {"id": target})
            if f.read_bytes()[:7] == b"FAKEMP4":
                frames = []
            else:
                frames = frames_mod.extract(f, outdir, 8, shot.get("seconds", 4))
            prompt = clip_checklist.build_prompt(shot, len(frames))
            ff = shot.get("first_frame")
            frames = ([str(p / ff)] if ff and (p / ff).exists() else []) + frames
        else:
            imgs = self._read(p, "images.json", {"images": []})
            spec = next((i for i in imgs["images"] if i["id"] == target), {"id": target})
            by = {i["id"]: i for i in imgs["images"]}
            refs = [(p / by[r]["out"]) for r in spec.get("refs", []) if r in by and (p / by[r]["out"]).exists()]
            prompt = image_checklist.build_prompt(spec, [r.name for r in refs])
            frames = [str(r) for r in refs] + [str(f)]
        raw = self.runner().vision(prompt, frames, {"max_tokens": 3500, "temperature": 0.2}, project_dir=p)
        res = {**clip_checklist.parse_review(raw["text"]), "cost": raw["cost"]}
        log = {**log, "model": raw["model"], "provider": raw["provider"], "cost_source": raw["cost_source"]}
        review = {k: res[k] for k in ("verdict", "findings", "summary")}
        review.update({"target": target, "model": raw["model"], "cost": res.get("cost", 0), "when": datetime.now().isoformat(timespec="seconds"),
                       "advisory": "A human still approves. A vision model cannot judge the spoken language."})
        project_mod.save_json(outdir, "review.json", review)
        costlog.append_log(p, {**log, "timestamp": datetime.now().isoformat(timespec="seconds"), "resolution": "", "cost": res.get("cost", 0), "result": "completed"})
        return {"kind": "review", "review": review}

    # ---------------------------------------------------------------- review outcomes
    def approve_shot(self, name, shot_id):
        p = self.pdir(name)
        doc = self._read(p, "shots.json")
        shot = next((s for s in doc["shots"] if s["id"] == shot_id), None) or (_ for _ in ()).throw(ServiceError("unknown shot"))
        done = [r for r in costlog.read_log(p) if r["shot"] == shot_id and r["stage"] == "final" and r["result"] == "completed"]
        if not done:
            raise ServiceError("no completed clip to approve")
        shot["final_ok"] = True
        shot["final_clip"] = f"clips/{shot_id}_final_a{done[-1]['attempt']}.mp4"
        project_mod.save_json(p, "shots.json", doc)
        return shot

    def discard(self, name, rel, reason=""):
        p = self.pdir(name)
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
        self._changed(name, "assets", "shots")
        return rec

    def restore(self, name, rel):
        try:
            out = discard_mod.restore_file(self.pdir(name), rel).relative_to(self.pdir(name)).as_posix()
        except (ValueError, FileNotFoundError, FileExistsError) as e:
            raise ServiceError(str(e)) from None
        self._changed(name, "assets", "shots")
        return out

    def costs(self, name):
        p = self.pdir(name)
        return {"split": costlog.split(p), "rows": costlog.read_log(p), "budget": self._read(p, "budget.json", {})}

    def sync(self, name):
        """Resolve clips left pending by a timeout: fetch real status/cost and save the clip."""
        p = self.pdir(name)
        rows, fixed = costlog.read_log(p), []
        for r in rows:
            if r["result"] == "pending" and r["job_id"]:
                req = {"seconds": int(r["seconds"] or 0), "resolution": r["resolution"] or "720p", "audio": False}
                try:
                    res = self.runner().fetch_video({"job_id": r["job_id"], "model": r["model"], "provider": r.get("provider") or "openrouter"}, req)
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
                import csv
                w = csv.DictWriter(fh, fieldnames=costlog.LOG_COLS)
                w.writeheader()
                w.writerows(rows)
        return {"resolved": fixed}
