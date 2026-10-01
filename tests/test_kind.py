import tests._hermetic  # noqa: F401
import json, tempfile, unittest, zipfile
from pathlib import Path
from aistudio import kind, importzip
from aistudio.service import Workspace

LOG = "timestamp,shot,stage,model,resolution,seconds,attempt,job_id,cost,result\n"
REAL_MP4 = b"\x00\x00\x00\x18ftypisom" + b"0" * 40
PLACEHOLDER = b"FAKEMP4\x04A"


def proj(clips=(), rows=(), sandbox=False):
    d = Path(tempfile.mkdtemp())
    (d / "clips").mkdir()
    for i, c in enumerate(clips):
        (d / "clips" / f"s{i}.mp4").write_bytes(c)
    (d / "cost_log.csv").write_text(LOG + "".join(f"2026-01-01T00:00:00,{shot},{stage},{model},720p,4,1,j,{cost},completed\n" for shot, stage, model, cost in rows))
    if sandbox:
        (d / "sandbox.json").write_text("{}")
    return d


class TestKind(unittest.TestCase):
    def test_classification(self):
        self.assertFalse(kind.is_test_project(proj()))                                           # empty project: ordinary
        self.assertTrue(kind.is_test_project(proj(clips=[PLACEHOLDER])))                          # only placeholder clips
        self.assertTrue(kind.is_test_project(proj(rows=[("s1", "image", "fake/image", 0.036)])))  # only fake-priced work
        self.assertFalse(kind.is_test_project(proj(clips=[REAL_MP4])))                            # a real clip
        self.assertFalse(kind.is_test_project(proj(rows=[("s1", "final", "google/veo-3.1-lite", 0.12)])))
        self.assertFalse(kind.is_test_project(proj(clips=[PLACEHOLDER, REAL_MP4])))               # mixed: real wins
        self.assertTrue(kind.is_test_project(proj(sandbox=True)))                                 # the Test pipeline switch
        self.assertTrue(kind.is_test_project(proj(rows=[("_ai", "chat", "google/gemma:free", 0)], sandbox=True)))   # real chat AI is allowed in a test pipeline
        self.assertFalse(kind.is_test_project(proj(clips=[REAL_MP4], sandbox=True)))              # marker contradicted by real media

    def test_listing_uses_the_files_not_the_app_mode(self):
        ws = Workspace(tempfile.mkdtemp())
        ws.create_project("real1")
        (ws.pdir("real1") / "clips" / "a.mp4").write_bytes(REAL_MP4)
        ws.create_project("play")
        (ws.pdir("play") / "clips" / "a.mp4").write_bytes(PLACEHOLDER)
        got = {p["name"]: p["test"] for p in ws.list_projects()}
        self.assertEqual(got, {"play": True, "real1": False})
        self.assertEqual((ws.overview("real1")["is_test"], ws.overview("play")["is_test"]), (False, True))


class TestImportClassification(unittest.TestCase):
    def zip_of(self, d, name="p"):
        f = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        with zipfile.ZipFile(f, "w") as z:
            for p in Path(d).rglob("*"):
                if p.is_file():
                    z.write(p, f"{name}/{p.relative_to(d)}")
        f.close()
        return f.name

    def base(self, d):
        (d / "Story.md").write_text("# s")
        (d / "shots.json").write_text(json.dumps({"aspect_ratio": "9:16", "audio": False, "shots": []}))
        (d / "images.json").write_text(json.dumps({"style": "", "images": []}))
        return d

    def test_wrong_test_marker_is_dropped_on_import(self):
        d = self.base(proj(clips=[REAL_MP4], rows=[("s1", "final", "google/veo-3.1-lite", 0.12)], sandbox=True))
        ws = Workspace(tempfile.mkdtemp())
        r = ws.import_project(self.zip_of(d), "real", "p.zip")
        self.assertFalse((ws.pdir("real") / "sandbox.json").exists())
        self.assertTrue(any("actual project" in n for n in r["notes"]))
        self.assertFalse(ws.overview("real")["is_test"])

    def test_real_project_is_reported_as_actual(self):
        d = self.base(proj(clips=[REAL_MP4]))
        r = Workspace(tempfile.mkdtemp()).import_project(self.zip_of(d), "r", "p.zip")
        self.assertTrue(any("actual project" in n for n in r["notes"]))

    def test_test_project_stays_test(self):
        d = self.base(proj(clips=[PLACEHOLDER], sandbox=True))
        ws = Workspace(tempfile.mkdtemp())
        r = ws.import_project(self.zip_of(d), "t", "p.zip")
        self.assertTrue((ws.pdir("t") / "sandbox.json").exists())
        self.assertTrue(any("test project" in n for n in r["notes"]))
        self.assertTrue(ws.overview("t")["is_test"])


if __name__ == "__main__":
    unittest.main()
