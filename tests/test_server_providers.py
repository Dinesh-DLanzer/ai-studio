import tests._hermetic  # noqa: F401
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
    from server.app import create_app
except ImportError:
    TestClient = None

H = {"x-aistudio-token": "tok"}


@unittest.skipIf(TestClient is None, "fastapi not installed")
class TestProviderRoutes(unittest.TestCase):
    def setUp(self):
        from aistudio.secrets import SecretStore
        d = Path(tempfile.mkdtemp())
        self.c = TestClient(create_app(d, token="tok", static_dir="/nonexistent", secret_store=SecretStore(d / "sec")))

    def test_requires_token_and_secret_routes_need_header(self):
        self.assertEqual(self.c.get("/api/providers").status_code, 401)
        self.assertEqual(self.c.post("/api/providers?token=tok", json={"type": "openai"}).status_code, 401)        # query token is not enough
        self.assertEqual(self.c.post("/api/providers", json={"type": "openai"}, headers=H).status_code, 200)
        self.assertEqual(self.c.put("/api/providers/openai/secret?token=tok", json={"api_key": "sk-x" * 5}).status_code, 401)

    def test_full_flow_and_no_secret_in_any_response(self):
        key = "sk-LEAKCANARY-1234567890"
        r = self.c.post("/api/providers", json={"type": "openai", "label": "OpenAI", "secret": {"api_key": key}}, headers=H)
        self.assertEqual(r.json()["id"], "openai")
        self.assertEqual(self.c.get("/api/provider-types", headers=H).json()["types"][0]["type"], "openrouter")
        r = self.c.put("/api/roles/chat", json={"chain": [{"provider": "openai", "model": "gpt-x"}]}, headers=H)
        self.assertEqual(r.json()["roles"]["chat"]["chain"][0]["model"], "gpt-x")
        r = self.c.put("/api/prices/openai/gpt-x", json={"kind": "text", "input_per_1m": 1, "output_per_1m": 2}, headers=H)
        self.assertEqual(r.status_code, 200)
        blobs = [self.c.get(u, headers=H).text for u in ("/api/providers", "/api/roles", "/api/models", "/api/providers/openai/models")]
        blobs.append(self.c.post("/api/providers/openai/test", headers=H).text)
        for b in blobs:
            self.assertNotIn("LEAKCANARY", b)
        self.assertEqual(self.c.delete("/api/providers/openai", headers=H).status_code, 400)      # used by chat
        self.assertEqual(self.c.delete("/api/providers/openai?force=1", headers=H).status_code, 200)

    def test_bad_input_is_400_not_500(self):
        self.assertEqual(self.c.post("/api/providers", json={"type": "nope"}, headers=H).status_code, 400)
        self.assertEqual(self.c.put("/api/roles/chat", json={"chain": [{"provider": "zz", "model": "m"}]}, headers=H).status_code, 400)
        self.assertEqual(self.c.put("/api/limits", json={"ai_cap_usd": -1}, headers=H).status_code, 400)
        self.assertEqual(self.c.get("/api/providers/zz/models", headers=H).status_code, 400)

    def test_cross_origin_blocked(self):
        r = self.c.put("/api/limits", json={"allow_paid": True}, headers={**H, "origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
