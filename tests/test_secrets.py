import os
import stat
import tempfile
import unittest
from pathlib import Path
from aistudio.secrets import SecretStore, SecretError

os.environ["AISTUDIO_NO_KEYRING"] = "1"


class FakeKeyring:
    def __init__(self, broken=False):
        self.d, self.broken = {}, broken

    def set_password(self, s, k, v):
        if self.broken:
            raise RuntimeError("no keychain")
        self.d[(s, k)] = v

    def get_password(self, s, k):
        return self.d.get((s, k))

    def delete_password(self, s, k):
        self.d.pop((s, k), None)


class TestSecrets(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()) / "sec"
        self.s = SecretStore(self.dir)

    def test_roundtrip_and_permissions(self):
        self.s.set("openai", {"api_key": " sk-abcdef123456 "})
        self.assertEqual(self.s.get("openai"), {"api_key": "sk-abcdef123456"})
        self.assertTrue(self.s.has("openai"))
        if os.name != "nt":                      # Windows ignores POSIX modes (the profile folder ACL protects the file there)
            self.assertEqual(stat.S_IMODE(self.s.path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(self.dir.stat().st_mode), 0o700)
        self.assertEqual(self.s.backend(), "file")

    def test_masked_never_reveals(self):
        self.s.set("k", {"access_key": "AKIAEXAMPLE1234", "secret_key": "short"})
        m = self.s.masked("k")
        self.assertEqual(m, {"set": True, "fields": {"access_key": "…1234", "secret_key": "…"}})
        self.assertFalse(self.s.masked("missing")["set"])

    def test_delete_and_missing(self):
        self.s.set("a", {"api_key": "x" * 20})
        self.s.delete("a")
        self.assertEqual(self.s.get("a"), {})

    def test_validation(self):
        for bad in ({}, {"api_key": ""}, {"Api Key": "v"}, {"api_key": 5}, "x"):
            with self.assertRaises(SecretError):
                self.s.set("a", bad)
        with self.assertRaises(SecretError):
            self.s.set("../evil", {"api_key": "x" * 20})

    def test_environment_variables_are_not_a_key_source(self):
        os.environ["MY_TEST_KEY_X"] = "envvalue-123456789"
        self.addCleanup(os.environ.pop, "MY_TEST_KEY_X", None)
        self.assertEqual(self.s.get("env:MY_TEST_KEY_X"), {})
        self.assertFalse(self.s.has("env:MY_TEST_KEY_X"))

    def test_redact(self):
        self.s.set("a", {"api_key": "sk-supersecret-value"})
        self.assertEqual(self.s.redact("boom sk-supersecret-value end"), "boom *** end")

    def test_keychain_and_fallback(self):
        kr = FakeKeyring()
        s = SecretStore(self.dir, keyring_mod=kr)
        s.set("a", {"api_key": "k" * 20})
        self.assertEqual(s.backend(), "keychain")
        self.assertFalse(self.s.path.exists())
        self.assertEqual(s.get("a"), {"api_key": "k" * 20})
        bad = SecretStore(self.dir, keyring_mod=FakeKeyring(broken=True))
        bad.set("b", {"api_key": "z" * 20})
        self.assertEqual(bad.backend(), "file")
        self.assertEqual(bad.get("b"), {"api_key": "z" * 20})


if __name__ == "__main__":
    unittest.main()
