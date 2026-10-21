"""Plan 14: versioned, provider-native pricing."""
import tests._hermetic as HERM  # noqa: F401  (first: no real keys, no network)
import json
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


class TestQuotesAgree(unittest.TestCase):
    """estimate, batch plan, proposal and execute all price one request the same way (card with minimum + per-reference charge)."""

    def setUp(self):
        from tests.test_spec import make, shots
        self.ws, self.p = make(self, {"fk|vid-a": {"references": {"max": 3}}})
        doc = json.loads((self.ws.settings_dir / "models.json").read_text())
        doc["prices"]["fk|vid-a"] = {"kind": "video", "per_second": {"720p": 0.10}, "minimum_seconds": 5, "per_reference_image": 0.05}
        (self.ws.settings_dir / "models.json").write_text(json.dumps(doc))
        shots(self.ws, ("s1", 4, {"refs": ["a", "b"]}))

    def test_four_agree(self):
        est = self.ws.estimate("demo", failure=0)
        self.assertEqual(est["per_shot"][0]["cost"], 0.6)      # billed 5s x 0.10 + 2 refs x 0.05
        self.assertEqual(self.ws.pipeline_domain._item_price(self.p, "clip", "s1"), (0.6, "vid-a"))
        self.ws.approve_budget("demo")
        prop = self.ws.propose("demo", "clip", "s1")
        self.assertEqual(prop["price"], 0.6)
        b = prop["summary"]["price_breakdown"]
        self.assertEqual((b["total"], b["base"], b["refs"], b["minimum_applied"]), (0.6, 0.5, 0.1, True))
        from aistudio.domain.spec import _age
        self.assertIn("no date", _age(self.ws.pricing(), {"ptype": "openrouter", "card": V})[0])      # undated: warned in spec / proposal warnings, never blocked
        self.assertEqual(_age(self.ws.pricing(), {"ptype": "fake", "card": V}), [])
        self.ws.approve_human("demo", prop["id"])
        self.assertEqual(self.ws.execute("demo", prop["id"])["kind"], "clip")

    def test_pricing_hash_changes_with_new_fields(self):
        h = self.ws.costs_domain.fingerprints(self.p)["pricing_hash"]
        doc = json.loads((self.ws.settings_dir / "models.json").read_text())
        doc["prices"]["fk|vid-a"]["minimum_seconds"] = 6
        (self.ws.settings_dir / "models.json").write_text(json.dumps(doc))
        self.assertNotEqual(h, self.ws.costs_domain.fingerprints(self.p)["pricing_hash"])


if __name__ == "__main__":
    unittest.main()
