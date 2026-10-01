import tests._hermetic  # noqa: F401  (first: no real keys, no network)
import json
import os
import tempfile
import unittest
from pathlib import Path
from aistudio.secrets import SecretStore
from aistudio.service import ServiceError, Workspace


def ws_new():
    root = Path(tempfile.mkdtemp())
    return Workspace(root, secrets=SecretStore(root / "sec"))


class TestProviders(unittest.TestCase):
    def setUp(self):
        self.ws = ws_new()

    def test_starts_with_fake_only(self):
        r = self.ws.providers_list()
        self.assertEqual([p["id"] for p in r["providers"]], ["fake"])
        self.assertEqual(r["providers"][0]["status"]["state"], "active")

    def test_create_with_secret_never_returns_it(self):
        p = self.ws.provider_create({"type": "google", "label": "Google", "secret": {"api_key": "AIzaSECRETSECRETSECRET1234"}})
        self.assertEqual(p["id"], "google")
        self.assertEqual(p["status"]["state"], "active")
        self.assertEqual(p["secret"], {"set": True, "fields": {"api_key": "…1234"}})
        self.assertNotIn("SECRETSECRET", json.dumps(self.ws.providers_list()))
        self.assertEqual(self.ws.provider_create({"type": "google", "label": "Google"})["id"], "google-2")

    def test_needs_key_then_key_added(self):
        p = self.ws.provider_create({"type": "anthropic"})
        self.assertEqual(p["status"]["state"], "needs_key")
        p = self.ws.provider_secret_put(p["id"], {"api_key": "sk-ant-xxxxxxxxxxxx"})
        self.assertEqual(p["status"]["state"], "active")
        with self.assertRaises(ServiceError):
            self.ws.provider_secret_put(p["id"], {"api_key": " "})

    def test_two_field_secret_for_kling(self):
        p = self.ws.provider_create({"type": "kling", "secret": {"access_key": "AK12345678", "secret_key": "SK12345678"}})
        self.assertEqual(set(p["secret"]["fields"]), {"access_key", "secret_key"})
        with self.assertRaises(ServiceError):
            self.ws.provider_secret_put(p["id"], {"access_key": "only-one"})

    def test_custom_requires_base_url(self):
        with self.assertRaises(ServiceError):
            self.ws.provider_create({"type": "custom", "label": "Local"})
        p = self.ws.provider_create({"type": "custom", "label": "Local", "base_url": "http://localhost:1234/v1"})
        self.assertEqual(p["status"]["state"], "active")          # keyless local servers are allowed

    def test_update_disable_and_fake_protected(self):
        p = self.ws.provider_create({"type": "openai", "secret": {"api_key": "sk-xxxxxxxxxxxxxxxx"}})
        self.assertEqual(self.ws.provider_update(p["id"], {"enabled": False})["status"]["state"], "inactive")
        with self.assertRaises(ServiceError):
            self.ws.provider_update("fake", {"enabled": False})
        with self.assertRaises(ServiceError):
            self.ws.provider_delete("fake")

    def test_delete_refused_when_used_unless_forced(self):
        p = self.ws.provider_create({"type": "google", "secret": {"api_key": "AIzaKEYKEYKEYKEYKEY1"}})
        self.ws.roles_put("chat", [{"provider": p["id"], "model": "gemini-2.5-flash"}])
        with self.assertRaises(ServiceError) as c:
            self.ws.provider_delete(p["id"])
        self.assertIn("chat", str(c.exception))
        self.assertEqual(self.ws.provider_delete(p["id"], force=True)["removed_from"], ["chat"])
        self.assertEqual(self.ws.roles_get()["roles"]["chat"]["chain"], [])
        self.assertFalse(self.ws.secrets.has(p["id"]))

    def test_provider_test_uses_adapter_and_redacts(self):
        p = self.ws.provider_create({"type": "fake"}) if False else None
        out = self.ws.provider_test("fake")
        self.assertTrue(out["result"]["ok"])
        g = self.ws.provider_create({"type": "google", "secret": {"api_key": "AIzaKEYKEYKEYKEYKEY1"}})
        out = self.ws.provider_test(g["id"])                          # no network in tests: fails, and the message must not leak the key
        self.assertFalse(out["result"]["ok"])
        self.assertEqual(out["provider"]["status"]["state"], "error")
        self.assertNotIn("KEYKEY", json.dumps(out))


class TestRolesApi(unittest.TestCase):
    def setUp(self):
        self.ws = ws_new()
        self.g = self.ws.provider_create({"type": "google", "secret": {"api_key": "AIzaKEYKEYKEYKEYKEY1"}})["id"]
        self.k = self.ws.provider_create({"type": "kling", "secret": {"access_key": "AK12345678", "secret_key": "SK12345678"}})["id"]

    def test_chain_validation_errors(self):
        with self.assertRaises(ServiceError):
            self.ws.roles_put("chat", [{"provider": self.k, "model": "kling-v1-6"}])      # kling cannot chat
        with self.assertRaises(ServiceError):
            self.ws.roles_put("video", [{"provider": "nope", "model": "m"}])

    def test_save_and_view_with_price_and_dearer_flag(self):
        self.ws.price_put(self.g, "veo-a", {"kind": "video", "per_second": {"720p": 0.05}})
        self.ws.price_put(self.k, "kling-b", {"kind": "video", "per_second": {"720p": 0.2}})
        r = self.ws.roles_put("video", [{"provider": self.g, "model": "veo-a"}, {"provider": self.k, "model": "kling-b"}])
        chain = r["roles"]["video"]["chain"]
        self.assertEqual([c["price"] for c in chain], ["$0.05/s", "$0.2/s"])
        self.assertEqual([c["dearer"] for c in chain], [False, True])
        self.assertEqual(self.ws.roles_get()["roles"]["image"]["chain"], [])

    def test_unpriced_model_is_flagged(self):
        r = self.ws.roles_put("image", [{"provider": self.g, "model": "mystery-image"}])
        self.assertFalse(r["roles"]["image"]["chain"][0]["priced"])

    def test_project_override(self):
        self.ws.create_project("demo")
        self.ws.roles_put("chat", [{"provider": self.g, "model": "gemini-a"}])
        r = self.ws.roles_put("chat", [{"provider": self.k and self.g, "model": "gemini-b"}], project="demo")
        self.assertTrue(r["roles"]["chat"]["overridden"])
        self.assertEqual(r["roles"]["chat"]["chain"][0]["model"], "gemini-b")
        self.assertEqual(self.ws.roles_get()["roles"]["chat"]["chain"][0]["model"], "gemini-a")
        r = self.ws.roles_put("chat", [], project="demo")
        self.assertFalse(r["roles"]["chat"]["overridden"])

    def test_limits_and_validation(self):
        self.assertEqual(self.ws.limits_put({"allow_paid": True, "ai_cap_usd": 2})["allow_paid"], True)
        with self.assertRaises(ServiceError):
            self.ws.limits_put({"ai_cap_usd": -5})

    def test_price_validation_and_suggest(self):
        with self.assertRaises(ServiceError):
            self.ws.price_put(self.g, "m", {"kind": "image", "per_image": -1})
        self.ws.model_add(self.g, "veo-3.1-lite-generate-preview", "video")
        m = next(x for x in self.ws.provider_models(self.g)["models"] if x["id"] == "veo-3.1-lite-generate-preview")
        self.assertFalse(m["priced"])
        self.assertEqual(m["suggest"]["from"], "google/veo-3.1-lite")      # one-click default from the built-in OpenRouter price
        self.assertTrue(m["custom"])

    def test_test_project_runs_with_no_provider_setup(self):
        ws = ws_new()
        ws.create_project("demo", test_pipeline=True)
        v = ws.runner().chat("chat", [{"role": "user", "content": "hello"}], project_dir=ws.pdir("demo"))
        self.assertEqual(v["text"], "FAKE: hello")

    def test_real_project_without_setup_says_what_to_do(self):
        ws = ws_new()
        ws.create_project("demo")
        with self.assertRaises(ServiceError) as c:
            ws._primary("video", ws.pdir("demo"))
        self.assertIn("Settings", str(c.exception))


if __name__ == "__main__":
    unittest.main()


class TestChainTest(unittest.TestCase):
    def test_unlistable_kinds_are_not_reported_as_failures(self):
        ws = ws_new()
        p = ws.provider_create({"type": "openrouter", "secret": {"api_key": "sk-or-xxxxxxxxxxxxxxxx"}})["id"]
        ws.roles_put("video", [{"provider": p, "model": "google/veo-3.1-lite"}])
        ws.roles_put("chat", [{"provider": p, "model": "no/such-chat-model"}])
        ws._model_cache = {p: (__import__("time").time(), [{"id": "a/b:free", "name": "AB", "capability": "chat"}])}     # what OpenRouter's /models returns
        v = ws.roles_test("video")["results"][0]
        self.assertTrue(v["ok"], v)
        self.assertIn("could not be verified", v["message"])
        c = ws.roles_test("chat")["results"][0]
        self.assertFalse(c["ok"])                                                 # text models CAN be checked, and this one does not exist
        self.assertIn("does not list", c["message"])


class TestSetupGate(unittest.TestCase):
    def test_fresh_workspace_needs_setup_then_clears(self):
        from aistudio.secrets import SecretStore
        import tempfile as tf
        os.environ.pop("AISTUDIO_ALL_TEST", None)
        ws = Workspace(tf.mkdtemp(), secrets=SecretStore(tf.mkdtemp(), keyring_mod=None))
        st = ws.setup_status()
        self.assertTrue(st["needed"])
        self.assertEqual(st["providers"]["ready"], [])
        self.assertFalse(st["roles"]["chat"]["ready"])
        ws.provider_create({"type": "openrouter", "label": "OR", "secret": {"api_key": "sk-or-test-1234567890"}})
        st = ws.setup_status()
        self.assertTrue(st["needed"])                       # a key alone is not enough: a chat model is needed too
        self.assertEqual(st["providers"]["ready"], ["or"])
        ws.roles_put("chat", [{"provider": "or", "model": "openrouter/free"}])
        st = ws.setup_status()
        self.assertFalse(st["needed"])
        self.assertTrue(st["roles"]["chat"]["ready"])
        self.assertFalse(st["roles"]["image"]["ready"])      # reported, but does not block

    def test_not_enforced_when_mode_is_set(self):
        import tempfile as tf
        os.environ["AISTUDIO_ALL_TEST"] = "1"
        try:
            self.assertFalse(Workspace(tf.mkdtemp()).setup_status()["needed"])
        finally:
            os.environ.pop("AISTUDIO_ALL_TEST", None)
