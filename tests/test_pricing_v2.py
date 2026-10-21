"""Plan 14: versioned, provider-native pricing."""
import unittest

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


if __name__ == "__main__":
    unittest.main()
