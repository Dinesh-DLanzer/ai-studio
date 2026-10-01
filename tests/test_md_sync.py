import tests._hermetic  # noqa: F401
import tempfile, unittest
from aistudio.service import Workspace


class TestMdSync(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(tempfile.mkdtemp())
        self.ws.create_project("demo")
        self.p = self.ws.pdir("demo")

    def test_brief_form_and_markdown_agree(self):
        self.ws.brief_put("demo", {"brand": "God Promo", "goal": "walk-ins"})
        md = self.ws.get_text("demo", "brief.md")
        self.assertIn("**Brand / business** (required): God Promo", md)
        self.ws.put_text("demo", "brief.md", md.replace("God Promo", "Suresh Textiles").replace("walk-ins", "_not answered yet_"))
        got = {f["key"]: f["value"] for f in self.ws.brief_get("demo")["fields"]}
        self.assertEqual(got["brand"], "Suresh Textiles")
        self.assertEqual(got["goal"], "")                                  # clearing in markdown clears the form
        self.ws.brief_put("demo", {"goal": "", "audience": "shop owners", "_clear": True})
        self.assertIn("shop owners", self.ws.get_text("demo", "brief.md"))

    def test_todo_markdown_round_trip_and_legacy_kept(self):
        (self.p / "TODO.md").write_text("# my own notes\n- [ ] something\n", encoding="utf-8")
        md = self.ws.get_text("demo", "TODO.md")
        self.assertTrue((self.p / "TODO.old.md").exists())
        self.assertIn("something", (self.p / "TODO.old.md").read_text(encoding="utf-8"))
        self.assertIn("Native speaker checks every spoken line", md)
        self.ws.put_text("demo", "TODO.md", md + "- [x] book the actor\n")
        t = self.ws.todos("demo")["manual"]
        self.assertTrue(any(x["title"] == "book the actor" and x["done"] for x in t))
        tid = next(x["id"] for x in t if x["title"] == "book the actor")
        self.ws.todo_toggle("demo", tid)
        self.assertIn("- [ ] book the actor", self.ws.get_text("demo", "TODO.md"))
        self.ws.put_text("demo", "TODO.md", md)                           # removing the line removes the task
        self.assertFalse(any(x["title"] == "book the actor" for x in self.ws.todos("demo")["manual"]))


if __name__ == "__main__":
    unittest.main()
