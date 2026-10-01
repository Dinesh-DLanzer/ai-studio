import json
import tempfile
import unittest
from pathlib import Path
from aistudio import migrate as M
from aistudio.providers import config as C


def ws(files=None):
    d = Path(tempfile.mkdtemp())
    for name, doc in (files or {}).items():
        (d / name).write_text(json.dumps(doc))
    return d


class TestMigrate(unittest.TestCase):
    def test_fresh_install_is_fake_only(self):
        d = ws()
        r = M.migrate(d)
        self.assertEqual(r["providers"], ["fake"])
        self.assertEqual(C.load_roles(d / "settings")["roles"]["chat"]["chain"], [])

    def test_openrouter_defaults_when_asked(self):
        d = ws()
        r = M.migrate(d, force_openrouter=True)
        self.assertEqual(r["providers"], ["openrouter", "fake"])
        roles = C.load_roles(d / "settings")
        self.assertEqual(roles["roles"]["video"]["chain"], [{"provider": "openrouter", "model": "google/veo-3.1-lite"}])
        self.assertEqual(roles["roles"]["image"]["chain"][0]["model"], "qwen/qwen-image-3")
        self.assertGreaterEqual(len(roles["roles"]["chat"]["chain"]), 3)
        self.assertNotIn("secret_ref", C.load_providers(d / "settings")[0])      # the key is added in Settings, never read from the environment

    def test_legacy_ai_settings_become_chains(self):
        d = ws({"ai_settings.json": {"chat": {"models": ["a/b:free", "c/d:free"]}, "verify": {"models": ["e/f:free"]}, "allow_paid": True, "ai_cap_usd": 2.5, "auto_verify": False}})
        M.migrate(d)
        roles = C.load_roles(d / "settings")
        self.assertEqual([m["model"] for m in roles["roles"]["chat"]["chain"]], ["a/b:free", "c/d:free"])
        self.assertEqual([m["model"] for m in roles["roles"]["verify"]["chain"]], ["e/f:free"])
        self.assertEqual((roles["allow_paid"], roles["ai_cap_usd"], roles["auto_verify"]), (True, 2.5, False))
        self.assertTrue((d / "ai_settings.json").exists())          # legacy file untouched

    def test_idempotent_and_dry_run(self):
        d = ws()
        self.assertFalse(M.migrate(d, dry_run=True)["migrated"])
        self.assertFalse((d / "settings").exists())
        self.assertTrue(M.migrate(d)["migrated"])
        self.assertFalse(M.migrate(d)["migrated"])


if __name__ == "__main__":
    unittest.main()
