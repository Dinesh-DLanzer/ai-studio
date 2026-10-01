import json
import tempfile
import unittest
from pathlib import Path
from aistudio.pricing import Pricing, validate_card, key

LEGACY = {"models": {"google/veo-3.1-lite": {"720p": {"audio": 0.05, "no_audio": 0.03}}, "bytedance/seedance-2.5": {"720p": 0.231}}}


class TestPricing(unittest.TestCase):
    def setUp(self):
        self.p = Pricing(LEGACY, {key("google", "veo-x"): {"kind": "video", "per_second": {"720p": 0.1}}})

    def test_card_sources(self):
        self.assertEqual(self.p.card("google", "google", "veo-x")["per_second"], {"720p": 0.1})        # override wins
        self.assertEqual(self.p.card("or", "openrouter", "bytedance/seedance-2.5")["kind"], "video")   # built-in
        self.assertTrue(self.p.is_free(self.p.card("or", "openrouter", "qwen/q:free")))
        self.assertEqual(self.p.card("fake", "fake", "fake/image")["per_image"], 0.036)
        self.assertIsNone(self.p.card("google", "google", "veo-3.1-new"))                               # unknown stays unknown
        self.assertIsNone(self.p.card("oa", "openai", "bytedance/seedance-2.5"))                         # built-ins are OpenRouter-only

    def test_video_price(self):
        c = self.p.card("or", "openrouter", "google/veo-3.1-lite")
        self.assertEqual(self.p.video_price(c, 4, "720p", True), 0.2)
        self.assertEqual(self.p.video_price(c, 4, "720p", False), 0.12)
        self.assertIsNone(self.p.video_price(c, 4, "1080p", True))
        self.assertIsNone(self.p.video_price(None, 4))

    def test_suggest(self):
        s = self.p.suggest("veo-3.1-lite-generate-preview")
        self.assertEqual(s["from"], "google/veo-3.1-lite")
        self.assertIsNone(self.p.suggest("totally-unknown"))

    def test_text_cost(self):
        self.assertEqual(self.p.text_cost({"kind": "text", "free": True}, {"input": 9, "output": 9}), 0.0)
        self.assertEqual(self.p.text_cost({"kind": "text", "input_per_1m": 1.0, "output_per_1m": 4.0}, {"input": 1000, "output": 500}), 0.003)
        self.assertEqual(self.p.text_cost({"kind": "text", "per_call": 0.001}, {}), 0.001)
        self.assertIsNone(self.p.text_cost(None, {}))

    def test_actual_cost_sources(self):
        self.assertEqual(self.p.actual_cost(0.5, 0.4), (0.5, "reported"))
        self.assertEqual(self.p.actual_cost(None, 0.4), (0.4, "computed"))
        self.assertEqual(self.p.actual_cost(None, None), (0.0, "unknown"))

    def test_validate_card(self):
        self.assertEqual(validate_card({"kind": "image", "per_image": 0.04}), [])
        self.assertEqual(validate_card({"kind": "video", "per_second": {"720p": {"audio": 1, "no_audio": 0.5}}}), [])
        for bad in ({}, {"kind": "image", "per_image": -1}, {"kind": "video", "per_second": {}}, {"kind": "video", "per_second": {"720p": "x"}}, {"kind": "text"}):
            self.assertTrue(validate_card(bad), bad)

    def test_load_from_files(self):
        d = Path(tempfile.mkdtemp())
        (d / "rates.json").write_text(json.dumps(LEGACY))
        (d / "models.json").write_text(json.dumps({"prices": {key("g", "m"): {"kind": "image", "per_image": 0.02}}}))
        p = Pricing.load(d / "rates.json", d)
        self.assertEqual(p.card("g", "google", "m")["per_image"], 0.02)
        self.assertEqual(Pricing.load(d / "none.json", d / "none").card("g", "google", "m"), None)


if __name__ == "__main__":
    unittest.main()
