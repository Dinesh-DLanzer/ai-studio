import tests._hermetic as HERM  # noqa: F401  (no real key or network in tests)
import json, tempfile, unittest
from pathlib import Path
from aistudio.service import Workspace, ServiceError
from tests.test_story_convert import MD


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 20
JPG_BYTES = b"\xff\xd8\xff\xe0" + b"0" * 20


class TestService(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.ws = Workspace(tempfile.mkdtemp())
        self.ws.create_project("demo")
        self.ws.put_text("demo", "Story.md", MD)
        self.ws.convert_story("demo")
        self.p = self.ws.pdir("demo")

    def go(self, kind, target, approve=True):
        prop = self.ws.propose("demo", kind, target, reveal_code=True)
        if approve:
            self.ws.approve("demo", prop["id"], prop["code"])
        return prop

    def budget(self, approved=True):
        self.ws.estimate("demo", 0.2)
        if approved:
            self.ws.approve_budget("demo")

    def test_overview_and_convert(self):
        o = self.ws.overview("demo")
        self.assertEqual([s["id"] for s in o["shots"]["shots"]], ["s01", "s02", "s03"])
        self.assertEqual(o["mode"], "test")
        self.assertEqual(self.ws.list_projects()[0]["shots"], 3)

    def test_no_run_without_budget(self):
        prop = self.go("image", "s01")
        with self.assertRaises(ServiceError) as c:
            self.ws.execute("demo", prop["id"])
        self.assertIn("budget not approved", str(c.exception))
        self.assertFalse((self.p / "stills" / "s01.png").exists())

    def test_agent_cannot_self_approve(self):
        prop = self.ws.propose("demo", "image", "s01")          # agent/MCP style: no code revealed
        self.assertNotIn("code", prop)
        with self.assertRaises(ServiceError):
            self.ws.approve("demo", prop["id"], "123456")
        self.budget()
        with self.assertRaises(ServiceError):
            self.ws.execute("demo", prop["id"])                 # still pending

    def test_full_flow(self):
        self.budget()
        self.ws.execute("demo", self.go("image", "s01")["id"])
        self.assertTrue((self.p / "stills" / "s01.png").exists())
        r = self.ws.execute("demo", self.go("clip", "s01")["id"])
        self.assertEqual(r["file"], "clips/s01_final_a1.mp4")
        self.assertEqual(r["cost"], 0.2)
        rv = self.ws.execute("demo", self.go("review", "s01")["id"])
        self.assertEqual(rv["review"]["verdict"], "pass")
        self.assertTrue((self.p / "checks" / "s01_final_a1" / "review.json").exists())
        self.ws.approve_shot("demo", "s01")
        self.assertTrue(self.ws.overview("demo")["shots"]["shots"][0]["final_ok"])
        c = self.ws.costs("demo")["split"]
        self.assertAlmostEqual(c["total"], 0.036 + 0.2 + 0.001)  # review billed at the fake vision cost
        self.ws.discard("demo", "clips/s01_final_a1.mp4", "test")
        c = self.ws.costs("demo")["split"]
        self.assertAlmostEqual(c["discarded"], 0.2)
        self.assertTrue((self.p / "clips" / "_discarded" / "s01_final_a1.mp4").exists())
        self.assertEqual(self.ws.restore("demo", "clips/_discarded/s01_final_a1.mp4"), "clips/s01_final_a1.mp4")

    def test_agent_proposal_human_approves_then_runs(self):
        self.budget()
        prop = self.ws.propose("demo", "image", "s01")                   # what MCP does
        self.assertNotIn("code", prop)
        self.assertIn("prompt", prop["summary"])
        with self.assertRaises(ServiceError):
            self.ws.execute("demo", prop["id"])                          # agent cannot run it yet
        self.ws.approve_human("demo", prop["id"])                        # the human clicks Approve in the UI
        self.assertTrue(self.ws.execute("demo", prop["id"])["file"].endswith("s01.png"))

    def test_changed_request_voids(self):
        self.budget()
        self.ws.execute("demo", self.go("image", "s01")["id"])
        prop = self.go("clip", "s01")
        doc = self.ws.overview("demo")["shots"]
        doc["shots"][0]["prompt"] = "CHANGED AFTER APPROVAL"
        self.ws.put_shots("demo", doc)
        with self.assertRaises(ServiceError):
            self.ws.execute("demo", prop["id"])

    def test_max_attempts_and_single_use(self):
        self.budget()
        self.ws.execute("demo", self.go("image", "s01")["id"])
        for i in range(3):
            prop = self.go("clip", "s01")
            self.ws.execute("demo", prop["id"])
            with self.assertRaises(ServiceError):
                self.ws.execute("demo", prop["id"])             # an approval works once
        with self.assertRaises(ServiceError) as c:
            self.ws.execute("demo", self.go("clip", "s01")["id"])
        self.assertIn("attempts", str(c.exception))

    def test_stop_loss(self):
        self.budget()
        b = json.loads((self.p / "budget.json").read_text())
        b["stop_loss"] = 0.1
        (self.p / "budget.json").write_text(json.dumps(b))
        self.ws.execute("demo", self.go("image", "s01")["id"])   # 0.036 fits
        with self.assertRaises(ServiceError) as c:
            self.ws.execute("demo", self.go("clip", "s01")["id"])  # 0.2 does not
        self.assertIn("stop-loss", str(c.exception))

    def test_bad_ids_and_paths(self):
        for bad in ("../x", "a/b", "", "x y"):
            with self.assertRaises(ServiceError):
                self.ws.pdir(bad)
            with self.assertRaises(ServiceError):
                self.ws.propose("demo", "image", bad)
        with self.assertRaises(ServiceError):
            self.ws.discard("demo", "../../etc/passwd")
        with self.assertRaises(ServiceError):
            self.ws.add_file("demo", "clips/x.png", b"x")
        with self.assertRaises(ServiceError):
            self.ws.add_file("demo", "stills/up1.png", b"not an image")          # content must be a real PNG/JPEG
        self.ws.add_file("demo", "stills/up1.png", PNG_BYTES)
        with self.assertRaises(ServiceError):
            self.ws.add_file("demo", "stills/up1.png", PNG_BYTES)                 # no silent overwrite

    def test_upload_replace_keeps_the_old_file(self):
        self.ws.add_file("demo", "stills/hero.png", PNG_BYTES)
        self.ws.add_file("demo", "stills/hero.jpg", JPG_BYTES, replace=True)   # replace with a different format
        st = self.p / "stills"
        self.assertFalse((st / "hero.png").exists())
        self.assertTrue((st / "hero.jpg").exists())
        self.assertTrue((st / "_discarded" / "hero.png").exists())              # old image kept
        self.assertEqual(self.ws.overview("demo")["discarded"][0]["reason"], "replaced by an upload")
        self.ws.add_file("demo", "stills/hero.png", PNG_BYTES, replace=True)   # extension follows the real content
        self.assertEqual(sorted(f.name for f in st.glob("hero.*")), ["hero.png"])
        self.ws.add_file("demo", "stills/fake.jpg", PNG_BYTES)                 # a PNG uploaded under .jpg is stored as .png
        self.assertTrue((st / "fake.png").exists())

    def test_other_image_formats_are_accepted_and_converted(self):
        import shutil, subprocess
        for bad in (b"<svg/>", b"%PDF-1.4", b""):
            with self.assertRaises(ServiceError):
                self.ws.add_file("demo", "stills/x.png", bad)
        with self.assertRaises(ServiceError):
            self.ws.add_file("demo", "stills/x.exe", PNG_BYTES)                # extension must be an image type
        if shutil.which("sips"):
            d = Path(tempfile.mkdtemp())
            (d / "a.png").write_bytes(__import__("base64").b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="))
            subprocess.run(["sips", "-s", "format", "gif", str(d / "a.png"), "--out", str(d / "a.gif")], capture_output=True)
            self.ws.add_file("demo", "stills/fromgif.gif", (d / "a.gif").read_bytes())
            self.assertEqual((self.p / "stills" / "fromgif.png").read_bytes()[:4], b"\x89PNG")

    def test_a_project_is_test_or_real_by_its_files_not_by_an_app_mode(self):
        import os
        self.assertTrue(self.ws.overview("demo")["is_test"])                   # AISTUDIO_ALL_TEST=1 (set in setUp) makes every project a test project
        os.environ.pop("AISTUDIO_ALL_TEST")
        self.assertFalse(self.ws.overview("demo")["is_test"])                  # an ordinary project is real
        self.assertEqual(self.ws.overview("demo")["mode"], "real")
        self.ws.create_project("practice", test_pipeline=True)
        self.assertTrue(self.ws.overview("practice")["is_test"])               # the Test pipeline switch makes a test project
        self.assertEqual(self.ws.overview("practice")["mode"], "test")
        self.assertFalse(hasattr(self.ws, "set_mode"))
        self.assertFalse(hasattr(self.ws, "config"))

