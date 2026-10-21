"""Plan 14: versioned, provider-native pricing."""
import unittest
from datetime import date
from pathlib import Path

from aistudio.pricing import Pricing, validate_card, key

V = {"kind": "video", "per_second": {"720p": 0.1}}


class TestCardFields(unittest.TestCase):
    def test_optional_fields(self):
        ok = {**V, "minimum_seconds": 4, "per_reference_image": 0.01, "retrieved_at": "2026-09-30", "source": "x"}
        self.assertEqual(validate_card(ok), [])
        for bad in ({"minimum_seconds": -1}, {"per_reference_image": "a"}, {"retrieved_at": "yesterday"}, {"source": 3}):
            self.assertTrue(validate_card({**V, **bad}), bad)

    def test_new_kinds(self):
        self.assertEqual(validate_card({"kind": "audio", "per_1k_chars": 0.015}), [])
        self.assertEqual(validate_card({"kind": "audio", "per_minute": 0.006}), [])
        self.assertEqual(validate_card({"kind": "utility", "per_run": 0.01}), [])
        self.assertTrue(validate_card({"kind": "audio"}))
        self.assertTrue(validate_card({"kind": "utility", "per_run": -1}))


LEGACY = {"models": {"x/v": {"720p": 0.1, "retrieved_at": "2026-09-30", "source": "openrouter pricing_skus"}}}


class TestMath(unittest.TestCase):
    def setUp(self):
        self.p = Pricing(LEGACY, {})
        self.card = {**V, "minimum_seconds": 5, "per_reference_image": 0.02, "retrieved_at": "2026-09-01"}

    def test_loader_strips_meta_and_keeps_it_on_card(self):
        c = self.p.card("or", "openrouter", "x/v")
        self.assertEqual(c["per_second"], {"720p": 0.1})
        self.assertEqual((c["retrieved_at"], c["source"]), ("2026-09-30", "openrouter pricing_skus"))
        self.assertEqual(self.p.video_price(c, 4), 0.4)

    def test_minimum_and_refs(self):
        self.assertEqual(self.p.video_price(V, 4), 0.4)
        self.assertEqual(self.p.video_price(self.card, 4), 0.5)               # billed as 5s
        self.assertEqual(self.p.video_price(self.card, 8), 0.8)
        self.assertEqual(self.p.video_price(self.card, 4, refs=3), 0.56)
        self.assertEqual(self.p.image_price({"kind": "image", "per_image": 0.036, "per_reference_image": 0.01}, 2), 0.056)
        self.assertEqual(self.p.image_price({"kind": "image", "per_image": 0.036}, 2), 0.036)

    def test_breakdown_total_equals_quote(self):
        b = self.p.breakdown(self.card, 4, "720p", False, refs=3, today=date(2026, 10, 21))
        self.assertEqual(b["total"], self.p.video_price(self.card, 4, "720p", False, 3))
        self.assertEqual((b["base"], b["refs"], b["minimum_applied"], b["billed_seconds"], b["age_days"]), (0.5, 0.06, True, 5, 50))
        self.assertAlmostEqual(b["base"] + b["refs"], b["total"])

    def test_age_unknown_and_warnings(self):
        t = date(2026, 10, 21)
        self.assertIsNone(self.p.breakdown(V, 4, today=t)["age_days"])
        self.assertIn("no date", self.p.age_warning(V, t))
        self.assertIn("50 days", self.p.age_warning(self.card, t))
        self.assertEqual(self.p.age_warning({**V, "retrieved_at": "2026-10-01"}, t), "")

    def test_rates_json_dated(self):
        import json
        for m, d in json.loads(Path("rates.json").read_text())["models"].items():
            self.assertTrue(d.get("retrieved_at") and d.get("source"), m)
            self.assertEqual(Pricing(json.loads(Path("rates.json").read_text())).card("o", "openrouter", m)["retrieved_at"], d["retrieved_at"])


if __name__ == "__main__":
    unittest.main()
