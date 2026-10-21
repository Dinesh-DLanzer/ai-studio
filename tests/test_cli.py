import tests._hermetic as HERM  # noqa: F401  (no real key or network in tests)
import json, tempfile, unittest, os
from aistudio import cli
from aistudio.service import Workspace
from tests.test_story_convert import MD


class TestCli(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.home = tempfile.mkdtemp()
        os.environ["AISTUDIO_HOME"] = self.home
        self.ws = Workspace(self.home)
        self.ws.create_project("demo"); self.ws.put_text("demo", "Story.md", MD); self.ws.convert_story("demo"); self.ws.estimate("demo", 0.2)
        self.lines = []

    def run_cli(self, argv, answer="yes"):
        return cli.main(argv, ask=lambda q: answer, out=self.lines.append)

    def test_budget_and_proposal_approval(self):
        self.run_cli(["approve-budget", "demo"], "no")
        self.assertFalse(self.ws.overview("demo")["budget"]["approved"])
        self.run_cli(["approve-budget", "demo"])
        self.assertTrue(self.ws.overview("demo")["budget"]["approved"])
        prop = self.ws.propose("demo", "image", "s01")
        self.run_cli(["approve", "demo", prop["id"]], "no")
        self.assertEqual(self.ws.proposal_status("demo", prop["id"])["status"], "pending")
        self.run_cli(["approve", "demo", prop["id"]], "yes")
        self.assertEqual(self.ws.proposal_status("demo", prop["id"])["status"], "approved")

    def test_delete_and_restore_project(self):
        # Interactive no cancels
        self.run_cli(["delete-project", "demo"], "no")
        self.assertTrue((self.ws.root / "projects" / "demo").is_dir())

        # Interactive yes trashes project
        self.run_cli(["delete-project", "demo"], "yes")
        self.assertFalse((self.ws.root / "projects" / "demo").exists())

        # List trash
        trash = self.ws.trash_list()
        self.assertEqual(len(trash), 1)
        tid = trash[0]["id"]

        # Restore trash with -y
        self.run_cli(["restore-trash", tid, "-y"])
        self.assertTrue((self.ws.root / "projects" / "demo").is_dir())

    def test_errors(self):
        self.assertEqual(self.run_cli(["pending", "nope"]), 1)


class TestCliFormatsAndBrandKits(unittest.TestCase):
    """The CLI of plan 19: create a project from a format and a brand kit, list both."""

    def setUp(self):
        HERM.all_test(self)
        self.home = tempfile.mkdtemp()
        old = os.environ.get("AISTUDIO_HOME")
        os.environ["AISTUDIO_HOME"] = self.home
        self.addCleanup(lambda: os.environ.__setitem__("AISTUDIO_HOME", old) if old is not None else os.environ.pop("AISTUDIO_HOME", None))
        self.ws = Workspace(self.home)
        self.lines = []

    def run_cli(self, argv, answer="yes"):
        return cli.main(argv, ask=lambda q: answer, out=self.lines.append)

    def text(self):
        return "\n".join(self.lines)

    def test_formats_are_listed(self):
        self.assertEqual(self.run_cli(["formats"]), 0)
        self.assertIn("instagram-reel", self.text())
        self.assertIn("9:16", self.text())
        self.lines.clear()
        self.assertEqual(self.run_cli(["formats", "--json"]), 0)
        ids = [f["id"] for f in json.loads(self.text())["formats"]]
        self.assertIn("product-ad", ids)

    def test_brand_kits_list_create_and_delete(self):
        self.assertEqual(self.run_cli(["brand-kits", "create", "Acme Brand", "--style-words", "clean, bright"]), 0)
        self.assertTrue((self.ws.root / "brand_kits" / "acme-brand" / "kit.json").is_file())
        self.assertEqual(self.run_cli(["brand-kits", "list"]), 0)
        self.assertIn("acme-brand", self.text())
        # a second kit with the same name is refused, not overwritten
        self.assertEqual(self.run_cli(["brand-kits", "create", "Acme Brand"]), 1)
        self.assertIn("error", self.text())
        # deleting needs a human "yes" (or -y) and moves the kit to the trash
        self.assertEqual(self.run_cli(["brand-kits", "delete", "acme-brand"], "no"), 0)
        self.assertIn("Not confirmed", self.text())
        self.assertTrue((self.ws.root / "brand_kits" / "acme-brand").is_dir())
        self.assertEqual(self.run_cli(["brand-kits", "delete", "acme-brand", "-y"]), 0)
        self.assertFalse((self.ws.root / "brand_kits" / "acme-brand").exists())
        self.assertTrue((self.ws.root / "brand_kits" / "_trash" / "acme-brand").is_dir())

    def test_create_with_a_format_and_a_brand_kit(self):
        self.run_cli(["brand-kits", "create", "Acme", "--style-words", "clean, bright"])
        self.assertEqual(self.run_cli(["create", "reel", "--format", "instagram-reel", "--brand-kit", "acme"]), 0)
        p = self.ws.pdir("reel")
        shots = json.loads((p / "shots.json").read_text(encoding="utf-8"))
        self.assertEqual(shots["format"], "instagram-reel")
        self.assertEqual(shots["aspect_ratio"], "9:16")
        self.assertEqual(shots["brand_kit"], "acme")
        self.assertTrue((p / "brand" / "kit.json").is_file())
        self.assertIn("Shot 01", (p / "Story.md").read_text(encoding="utf-8"))

    def test_create_a_blank_project_is_unchanged(self):
        self.assertEqual(self.run_cli(["create", "plain"]), 0)
        p = self.ws.pdir("plain")
        shots = json.loads((p / "shots.json").read_text(encoding="utf-8"))
        self.assertEqual(shots["aspect_ratio"], "9:16")
        self.assertEqual(shots["audio"], False)
        self.assertNotIn("format", shots)
        self.assertFalse((p / "edit.json").exists())

    def test_an_unknown_format_or_kit_is_an_error(self):
        self.assertEqual(self.run_cli(["create", "bad", "--format", "nope"]), 1)
        self.assertIn("not found", self.text())
        self.assertFalse((self.ws.root / "projects" / "bad").exists())
        self.assertEqual(self.run_cli(["create", "bad", "--brand-kit", "nope"]), 1)
        self.assertFalse((self.ws.root / "projects" / "bad").exists())


if __name__ == "__main__":
    unittest.main()
