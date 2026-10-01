import json, tempfile, unittest
from pathlib import Path
from aistudio.providers import registry as R


class TestRegistry(unittest.TestCase):
    def test_default_valid(self):
        cfg = R.default_config()
        self.assertEqual(R.validate_config(cfg), [])
        self.assertEqual(cfg["mode"], "fake")
        self.assertEqual(len(cfg["providers"]), 7)

    def test_pick(self):
        cfg = R.default_config()
        for k in ("llm", "image", "video", "vision"):
            self.assertEqual(R.pick(cfg, k)["name"], "fake-" + k)
        cfg["mode"] = "real"
        self.assertEqual(R.pick(cfg, "video")["model"], "google/veo-3.1-lite")
        self.assertEqual(R.pick(cfg, "image")["name"], "openrouter-image")
        self.assertEqual(R.pick(cfg, "llm")["name"], "fake-llm")
        del cfg["defaults"]["video"]
        with self.assertRaises(KeyError):
            R.pick(cfg, "video")

    def test_validate_errors(self):
        base = R.default_config()
        for mut in (lambda c: c.update(mode="maybe"),
                    lambda c: c["providers"].append(dict(c["providers"][0])),
                    lambda c: c["providers"][0].update(kind="audio"),
                    lambda c: c["providers"][0].update(model=""),
                    lambda c: c["defaults"].update(video="nope"),
                    lambda c: c["defaults"].update(video="openrouter-image")):
            cfg = json.loads(json.dumps(base))
            mut(cfg)
            self.assertTrue(R.validate_config(cfg), cfg)

    def test_load_save(self):
        p = Path(tempfile.mkdtemp()) / "providers.json"
        self.assertEqual(R.load_config(p), R.default_config())
        cfg = R.default_config()
        cfg["mode"] = "real"
        R.save_config(p, cfg)
        self.assertEqual(R.load_config(p)["mode"], "real")
        cfg["mode"] = "bad"
        with self.assertRaises(ValueError):
            R.save_config(p, cfg)
        p.write_text('{"mode": "bad", "providers": [], "defaults": {}}')
        with self.assertRaises(ValueError):
            R.load_config(p)


if __name__ == "__main__":
    unittest.main()
