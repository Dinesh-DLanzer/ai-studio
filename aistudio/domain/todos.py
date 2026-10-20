"""Todo domain operations and markdown synchronization."""
import hashlib
import re

from aistudio import chat as chat_mod, project as project_mod
from aistudio.domain.common import MD_MARK, ServiceError


class TodoDomain:
    def __init__(self, ws):
        self.ws = ws

    def _todo_store(self, p):
        t = self.ws._read(p, "todos.json")
        if t is None:
            t = [
                {"id": "lang", "title": "Native speaker checks every spoken line", "done": False},
                {"id": "assets", "title": "Gather logo, colours and font for the editor", "done": False},
                {"id": "edit", "title": "Edit: trim, on-screen text, end card, music, AI label", "done": False},
            ]
            project_mod.save_json(p, "todos.json", t)
        return t

    def todos(self, name):
        p = self.ws.pdir(name)
        shots = self.ws._read(p, "shots.json", {"shots": []})["shots"]
        images = self.ws._read(p, "images.json", {"images": []})["images"]
        b = self.ws._read(p, "budget.json", {})
        bp = chat_mod.progress(self.ws._read(p, "brief.json", {}))
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
        p = self.ws.pdir(name)
        title = str(title).strip()[:120]
        if not title:
            raise ServiceError("empty task")
        t = self._todo_store(p)
        t.append({"id": "t" + hashlib.sha1((title + str(len(t))).encode()).hexdigest()[:8], "title": title, "done": False})
        project_mod.save_json(p, "todos.json", t)
        self.ws._changed(name, "todos")
        self.ws._sync_md(name, "TODO.md")
        return self.todos(name)

    def todo_toggle(self, name, tid):
        p = self.ws.pdir(name)
        t = self._todo_store(p)
        item = next((x for x in t if x["id"] == tid), None) or (_ for _ in ()).throw(ServiceError("unknown task"))
        item["done"] = not item["done"]
        project_mod.save_json(p, "todos.json", t)
        self.ws._changed(name, "todos")
        self.ws._sync_md(name, "TODO.md")
        return self.todos(name)

    def todo_remove(self, name, tid):
        p = self.ws.pdir(name)
        project_mod.save_json(p, "todos.json", [x for x in self._todo_store(p) if x["id"] != tid])
        self.ws._changed(name, "todos")
        self.ws._sync_md(name, "TODO.md")
        return self.todos(name)

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
        p = self.ws.pdir(name)
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
        self.ws._changed(name, "todos")
