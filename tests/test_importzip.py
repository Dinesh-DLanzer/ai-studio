import tests._hermetic  # noqa: F401
import json, os, stat, tempfile, unittest, zipfile
from pathlib import Path
from aistudio import importzip
from aistudio.service import Workspace
try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    HAVE = True
except Exception:
    HAVE = False

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40
MP4 = b"\x00\x00\x00\x18ftypisom" + b"0" * 40
SHOTS = {"aspect_ratio": "9:16", "audio": False, "shots": [{"id": "s01", "model": "m", "seconds": 4, "prompt": "p", "final_ok": True, "final_clip": "clips/s01_final_a1.mp4"}]}
IMAGES = {"style": "", "images": [{"id": "hero", "kind": "character", "out": "stills/hero.png", "prompt": "p", "refs": []}]}


def build(files, top="demo", extra=None):
    """Write a zip to a temp file.  files: {path: bytes|str|dict}."""
    f = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items():
            data = json.dumps(v) if isinstance(v, (dict, list)) else v
            z.writestr(f"{top}/{k}" if top else k, data)
        for info, data in (extra or []):
            z.writestr(info, data)
    f.close()
    return f.name


def good(**over):
    files = {"Story.md": "# s", "shots.json": SHOTS, "images.json": IMAGES, "stills/hero.png": PNG, "clips/s01_final_a1.mp4": MP4,
             "budget.json": {"estimate": 1.0, "approved": True}, "proposals.json": [{"id": "x", "approved": True}], "cost_log.csv": "a,b\n1,2\n"}
    files.update(over)
    return {k: v for k, v in files.items() if v is not None}


class TestImport(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(tempfile.mkdtemp())

    def refused(self, zp, name=None, *needles):
        with self.assertRaises(importzip.ImportError_) as cm:
            self.ws.import_project(zp, name, "x.zip")
        text = " | ".join(cm.exception.problems)
        for n in needles:
            self.assertIn(n, text)
        self.assertEqual(self.ws.list_projects(), [])                    # nothing installed
        self.assertFalse(list((self.ws.root / "_import_tmp").glob("*")) if (self.ws.root / "_import_tmp").exists() else [])   # nothing left behind
        return cm.exception.problems

    def test_good_zip_imports_and_drops_approvals(self):
        r = self.ws.import_project(build(good()), None, "x.zip")
        self.assertEqual(r["name"], "demo")
        p = self.ws.pdir("demo")
        self.assertTrue((p / "clips" / "s01_final_a1.mp4").exists() and (p / "stills" / "hero.png").exists())
        self.assertFalse((p / "proposals.json").exists())
        self.assertFalse(json.loads((p / "budget.json").read_text())["approved"])
        self.assertEqual(len(r["notes"]), 3)                                  # actual project, approvals dropped, budget reset
        self.assertTrue(any("actual project" in n for n in r["notes"]))
        self.assertEqual(self.ws.overview("demo")["shots"]["shots"][0]["id"], "s01")

    def test_roundtrip_with_real_export(self):
        self.ws.create_project("orig")
        p = self.ws.pdir("orig")
        (p / "clips" / "a.mp4").write_bytes(MP4)
        (p / "audio").mkdir()
        (p / "audio" / "m.mp3.rejected").write_bytes(b"junk")          # leftovers of ours are skipped, not fatal
        z = self.ws.export_project("orig")
        r = self.ws.import_project(z, "copy", "orig.zip")
        z.unlink()
        self.assertEqual(r["name"], "copy")
        self.assertTrue((self.ws.pdir("copy") / "clips" / "a.mp4").exists())
        self.assertFalse((self.ws.pdir("copy") / "audio" / "m.mp3.rejected").exists())

    def test_flat_zip_and_name_rules(self):
        r = self.ws.import_project(build(good(), top=""), "flat", "whatever.zip")
        self.assertEqual(r["name"], "flat")
        self.assertEqual(importzip.derive_name("My Ad (v2).zip", []), "My-Ad-v2")
        self.assertEqual(importzip.derive_name("x.zip", ["tea"]), "tea")
        self.refused_name = None
        for bad in ("../x", "a b", "a" * 65):
            with self.assertRaises(importzip.ImportError_):
                self.ws.import_project(build(good()), bad, "x.zip")
        with self.assertRaises(importzip.ImportError_) as cm:
            self.ws.import_project(build(good()), "flat", "x.zip")
        self.assertIn("already exists", str(cm.exception))

    def test_not_a_zip_and_empty(self):
        f = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        f.write(b"not a zip at all")
        f.close()
        self.refused(f.name, None, "not a zip")
        self.refused(build({}), None, "empty")

    def test_unsafe_entries(self):
        self.refused(build(good(), extra=[("../evil.json", "{}")]), None, "safe relative path")
        self.refused(build(good(), extra=[("/abs.json", "{}")]), None, "safe relative path")
        if os.name != "nt":                       # zipfile turns backslashes into separators when reading on Windows
            self.refused(build(good(), extra=[("demo/a\\b.json", "{}")]), None, "backslash")
        info = zipfile.ZipInfo("demo/link.txt")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.refused(build(good(), extra=[(info, "/etc/passwd")]), None, "symbolic link")

    def test_file_types_and_magic(self):
        self.refused(build(good(**{"run.sh": "rm -rf /", "x.exe": b"MZ", "page.html": "<script>"})), None, "run.sh", "x.exe", "page.html")
        self.refused(build(good(**{"clips/fake.mp4": b"hello this is text"})), None, "fake.mp4: is not a real mp4")
        self.refused(build(good(**{"stills/hero.png": b"GIF89a"})), None, "hero.png: is not a real png")
        self.refused(build(good(**{"clips/empty.mp4": b""})), None, "empty.mp4")

    def test_json_and_schema_validation(self):
        self.refused(build(good(**{"shots.json": "{broken"})), None, "shots.json: is not valid JSON")
        bad = dict(SHOTS, shots=[{"id": "s01", "model": "m", "seconds": -1, "prompt": ""}])
        self.refused(build(good(**{"shots.json": bad})), None, "seconds must be an int")
        self.refused(build(good(**{"images.json": {"images": [{"id": "a", "kind": "weird", "out": "x.gif", "prompt": "p", "refs": ["zzz"]}]}})), None, "images.json")
        self.refused(build(good(**{"edit.json": {"aspect": "4:3"}})), None, "edit.json")
        self.refused(build(good(**{"edit.json": {"tracks": {"video": [{"id": "v", "src": "clips/ghost.mp4", "in": 0, "out": 2}]}}})), None, "not in the zip")
        self.refused(build(good(**{"shots.json": dict(SHOTS, shots=[dict(SHOTS["shots"][0], final_clip="../../x.mp4")])})), None, "not a safe path")
        self.refused(build(good(**{"shots.json": dict(SHOTS, shots=[dict(SHOTS["shots"][0], final_clip="clips/missing.mp4")])})), None, "missing.mp4")
        self.refused(build({"notes.txt": "hi"}), None, "does not look like an AI Studio project")

    def test_all_problems_reported_together(self):
        probs = self.refused(build(good(**{"a.sh": "x", "shots.json": "{"})))
        self.assertGreaterEqual(len(probs), 2)

    def test_limits(self):
        old = dict(importzip.LIMITS)
        try:
            importzip.LIMITS["files"] = 3
            self.refused(build(good()), None, "entries")
            importzip.LIMITS.update(old)
            importzip.LIMITS["total"] = 10
            self.refused(build(good()), None, "limit")
            importzip.LIMITS.update(old)
            importzip.LIMITS["depth"] = 0
            self.refused(build(good()), None, "too deep")
        finally:
            importzip.LIMITS.update(old)

    def test_fake_mode_placeholder_clip_is_accepted(self):
        z = build(good(**{"clips/s01_final_a1.mp4": b"FAKEMP4\x04A"}))
        self.assertEqual(self.ws.import_project(z, None, "x.zip")["name"], "demo")

    def test_junk_is_ignored(self):
        z = build(good(), extra=[("__MACOSX/demo/._a", "x"), ("demo/.DS_Store", "x")])
        self.assertEqual(self.ws.import_project(z, None, "x.zip")["name"], "demo")


@unittest.skipUnless(HAVE, "needs the venv with fastapi + httpx")
class TestRoute(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.c = TestClient(create_app(self.root, token="tok", static_dir="/nonexistent"))
        self.H = {"x-aistudio-token": "tok"}

    def post(self, zp, **q):
        qs = "&".join(f"{k}={v}" for k, v in q.items())
        return self.c.post(f"/api/projects/import?{qs}", content=Path(zp).read_bytes(), headers=self.H)

    def test_auth_import_and_errors(self):
        self.assertEqual(self.c.post("/api/projects/import", content=b"x").status_code, 401)
        r = self.post(build(good()), filename="demo.zip")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["name"], "demo")
        self.assertEqual(len(self.c.get("/api/projects", headers=self.H).json()["projects"]), 1)
        r = self.post(build(good()), filename="demo.zip")
        self.assertEqual(r.status_code, 400)
        self.assertIn("already exists", r.json()["detail"])
        r = self.post(build(good(**{"x.exe": b"MZ"})), name="other")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(any("x.exe" in p for p in r.json()["problems"]))
        self.assertEqual(len(self.c.get("/api/projects", headers=self.H).json()["projects"]), 1)


if __name__ == "__main__":
    unittest.main()
