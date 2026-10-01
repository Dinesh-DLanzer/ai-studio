import tests._hermetic  # noqa: F401
import json, tempfile, unittest
from pathlib import Path
from aistudio import aisettings as A


class TestAiSettings(unittest.TestCase):
    def test_defaults_are_free_and_valid(self):
        d = A.defaults()
        self.assertEqual(A.validate(d), [])
        self.assertFalse(d["allow_paid"])
        self.assertTrue(all(m.endswith(":free") or m == "openrouter/free" for r in A.ROLES for m in d[r]["models"]))

    def test_paid_needs_the_switch(self):
        d = A.defaults()
        d["chat"]["models"] = ["openai/gpt-5"]
        self.assertTrue(any("Allow paid" in e for e in A.validate(d)))
        d["allow_paid"] = True
        self.assertEqual(A.validate(d), [])

    def test_validation_errors(self):
        d = A.defaults()
        for mut in (lambda s: s["chat"].update(models=[]), lambda s: s["verify"].update(models=["a b:free"]),
                    lambda s: s["chat"].update(models=["x/y:free"] * 2), lambda s: s.update(ai_cap_usd=-1), lambda s: s.update(ai_cap_usd=1000),
                    lambda s: s.update(allow_paid="yes"), lambda s: s["chat"].update(models=["x/y:free"] * 7), lambda s: s.update(ai_cap_usd=True)):
            s = json.loads(json.dumps(d)); mut(s)
            self.assertTrue(A.validate(s), s)
        self.assertTrue(A.validate([]))

    def test_load_save_roundtrip(self):
        p = Path(tempfile.mkdtemp()) / "ai_settings.json"
        self.assertEqual(A.load(p), A.defaults())
        s = A.defaults(); s.update(allow_paid=True, ai_cap_usd=2); s["verify"]["models"] = ["google/gemini-2.5-flash-lite", "qwen/qwen3.8-27b:free"]
        A.save(p, s)
        self.assertEqual(A.load(p)["verify"]["models"][0], "google/gemini-2.5-flash-lite")
        s["allow_paid"] = False
        with self.assertRaises(ValueError):
            A.save(p, s)                                      # refused, file unchanged
        self.assertTrue(A.load(p)["allow_paid"])
        p.write_text("{not json")
        self.assertEqual(A.load(p), A.defaults())

    def test_nothing_is_overridden_from_the_environment(self):
        import os
        d = A.defaults()
        os.environ["AISTUDIO_CHAT_MODELS"], os.environ["AISTUDIO_ALLOW_PAID_CHAT"] = "a/b:free", "1"
        try:
            out, locked = A.effective(d)
        finally:
            del os.environ["AISTUDIO_CHAT_MODELS"], os.environ["AISTUDIO_ALLOW_PAID_CHAT"]
        self.assertEqual((out, locked), (d, []))

    def test_catalog(self):
        api = {"data": [
            {"id": "openai/gpt-5", "name": "GPT-5", "pricing": {"prompt": "0.000005", "completion": "0.00002"}, "architecture": {"output_modalities": ["text"]}, "context_length": 400000},
            {"id": "nvidia/x:free", "name": "X", "pricing": {"prompt": "0", "completion": "0"}, "architecture": {"output_modalities": ["text"]}},
            {"id": "black-forest-labs/flux", "pricing": {"prompt": "0", "completion": "0"}, "architecture": {"output_modalities": ["image"]}},
            {"id": "openrouter/auto", "pricing": {"prompt": "-1", "completion": "-1"}}, {"id": "bad id!", "pricing": {}},
            {"id": "cheap/model", "pricing": {"prompt": "0.0000001", "completion": "0.0000004"}, "architecture": {"output_modalities": ["text"]}}]}
        rows = A.parse_catalog(api)
        self.assertEqual([r["id"] for r in rows], ["nvidia/x:free", "cheap/model", "openai/gpt-5"])
        self.assertEqual((rows[0]["free"], rows[2]["free"], rows[2]["prompt_per_m"], rows[2]["completion_per_m"]), (True, False, 5.0, 20.0))
        self.assertTrue(all(r["free"] for r in A.static_catalog()))


if __name__ == "__main__":
    unittest.main()
