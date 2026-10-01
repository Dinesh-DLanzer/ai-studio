import json, tempfile, unittest
from pathlib import Path
from aistudio import project as P


class TestProject(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_create(self):
        p = P.create_project(self.root, "demo")
        self.assertTrue((p / "clips").is_dir() and (p / "stills").is_dir())
        for f in ("brief.md", "Story.md", "TODO.md"):
            self.assertIn("demo", (p / f).read_text(encoding="utf-8"))
        self.assertEqual(json.loads((p / "shots.json").read_text()), {"aspect_ratio": "9:16", "audio": False, "shots": []})
        self.assertEqual(json.loads((p / "images.json").read_text()), {"style": "", "images": []})

    def test_create_errors(self):
        P.create_project(self.root, "demo")
        with self.assertRaises(FileExistsError):
            P.create_project(self.root, "demo")
        for bad in ("", "a/b", "..", "a\\b", "x..y"):
            with self.assertRaises(ValueError):
                P.create_project(self.root, bad)

    def test_json_roundtrip_tamil(self):
        p = P.create_project(self.root, "demo")
        data = {"line": "கடை இருக்கு"}
        P.save_json(p, "x.json", data)
        self.assertIn("கடை", (p / "x.json").read_text(encoding="utf-8"))
        self.assertEqual(P.load_json(p, "x.json"), data)

    def good_shot(self, **kw):
        s = {"id": "s01", "model": "google/veo-3.1-lite", "seconds": 4, "prompt": "x"}
        s.update(kw)
        return s

    def test_validate_shots_ok(self):
        self.assertEqual(P.validate_shots({"shots": [self.good_shot(audio=True, resolution="720p")]}), [])

    def test_validate_shots_errors(self):
        for bad in ({"shots": "no"}, {"shots": [self.good_shot(id="")]}, {"shots": [self.good_shot(), self.good_shot()]},
                    {"shots": [self.good_shot(seconds=0)]}, {"shots": [self.good_shot(seconds="4")]},
                    {"shots": [self.good_shot(prompt="")]}, {"shots": [self.good_shot(audio="yes")]},
                    {"shots": [self.good_shot(resolution="4k")]}, {"shots": [self.good_shot(model=3)]}):
            errs = P.validate_shots(bad)
            self.assertTrue(errs and all(isinstance(e, str) and e for e in errs), bad)

    def img(self, **kw):
        d = {"id": "a", "kind": "character", "out": "stills/a.png", "prompt": "p", "refs": []}
        d.update(kw)
        return d

    def test_validate_images(self):
        ok = {"images": [self.img(), self.img(id="b", kind="frame", out="stills/b.jpg", refs=["a"])]}
        self.assertEqual(P.validate_images(ok), [])
        for bad in ({"images": [self.img(kind="x")]}, {"images": [self.img(out="stills/a.gif")]},
                    {"images": [self.img(), self.img()]}, {"images": [self.img(refs=["zzz"])]},
                    {"images": [self.img(prompt="")]}, {"images": "no"},
                    {"images": [self.img(id=str(i)) for i in range(6)] + [self.img(id="r", refs=[str(i) for i in range(5)])]}):
            self.assertTrue(P.validate_images(bad), bad)


if __name__ == "__main__":
    unittest.main()
