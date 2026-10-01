import json
import tempfile
import unittest
from pathlib import Path
from aistudio.providers import config as C

P = [{"id": "g", "type": "google", "label": "Google", "base_url": "", "enabled": True},
     {"id": "k", "type": "kling", "label": "Kling", "base_url": "", "enabled": True}]


class TestConfig(unittest.TestCase):
    def test_provider_types_listed(self):
        types = {t["type"]: t for t in C.provider_types()}
        self.assertIn("video", types["google"]["capabilities"])
        self.assertEqual(types["kling"]["fields"], ["access_key", "secret_key"])
        self.assertTrue(types["custom"]["base_url"])
        self.assertEqual(types["anthropic"]["capabilities"], ["chat", "vision"])

    def test_validate_providers(self):
        self.assertEqual(C.validate_providers(P), [])
        bad = C.validate_providers([{"id": "A B", "type": "x", "label": "l"}, {"id": "g", "type": "google", "label": ""}, {"id": "g", "type": "google", "label": "d"},
                                    {"id": "c", "type": "custom", "label": "c", "base_url": "ftp://x"}])
        self.assertEqual(len(bad), 5)

    def test_chain_validation(self):
        ok = [{"provider": "g", "model": "veo-3.1"}]
        self.assertEqual(C.validate_chain("video", ok, P), [])
        self.assertIn("cannot do chat", C.validate_chain("chat", [{"provider": "k", "model": "kling-v1"}], P)[0])
        self.assertIn("unknown provider", C.validate_chain("chat", [{"provider": "zz", "model": "m"}], P)[0])
        self.assertIn("twice", C.validate_chain("chat", ok + ok, P)[0])
        self.assertTrue(C.validate_chain("chat", [{"provider": "g", "model": "m"}] * 1 + [{"provider": "g", "model": f"m{i}"} for i in range(9)], P))
        self.assertTrue(C.validate_chain("nope", [], P))

    def test_roles_validation_and_defaults(self):
        d = C.default_roles()
        self.assertEqual(C.validate_roles(d, P), [])
        d["roles"]["chat"]["policy"]["retries"] = 9
        d["ai_cap_usd"] = -1
        self.assertEqual(len(C.validate_roles(d, P)), 2)

    def test_save_load_roundtrip_and_override(self):
        d = Path(tempfile.mkdtemp())
        C.save_providers(d, P)
        self.assertEqual(C.load_providers(d), P)
        doc = C.default_roles()
        doc["roles"]["video"]["chain"] = [{"provider": "g", "model": "veo-3.1"}, {"provider": "k", "model": "kling-v1-6"}]
        C.save_roles(d, doc, P)
        self.assertEqual(C.load_roles(d)["roles"]["video"]["chain"][1]["model"], "kling-v1-6")
        with self.assertRaises(ValueError):
            C.save_roles(d, {"roles": {"chat": {"chain": [{"provider": "k", "model": "x"}]}}}, P)
        proj = Path(tempfile.mkdtemp())
        (proj / "roles.override.json").write_text(json.dumps({"roles": {"video": {"chain": [{"provider": "k", "model": "kling-v1-6"}]}}}))
        self.assertEqual(C.effective_roles(d, proj)["roles"]["video"]["chain"], [{"provider": "k", "model": "kling-v1-6"}])
        self.assertEqual(len(C.effective_roles(d)["roles"]["video"]["chain"]), 2)

    def test_defaults_when_missing_or_corrupt(self):
        d = Path(tempfile.mkdtemp())
        self.assertEqual(C.load_providers(d)[0]["type"], "fake")
        (d / "roles.json").write_text("{not json")
        self.assertEqual(C.load_roles(d)["roles"]["chat"]["chain"], [])


if __name__ == "__main__":
    unittest.main()
