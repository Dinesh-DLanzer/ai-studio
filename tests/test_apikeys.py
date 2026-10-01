import tests._hermetic  # noqa: F401
import json, tempfile, unittest
from pathlib import Path
from aistudio import apikeys
try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    from server import api_docs
    HAVE = True
except Exception:
    HAVE = False
from tests.test_story_convert import MD


class TestKeyStore(unittest.TestCase):
    def test_create_verify_revoke_and_never_stored_in_clear(self):
        d = tempfile.mkdtemp()
        rec, key = apikeys.create(d, "my script")
        self.assertTrue(key.startswith("aisk_") and len(key) > 30)
        raw = (Path(d) / "settings" / "api_keys.json").read_text()
        self.assertNotIn(key, raw)                                              # only a hash is stored
        self.assertEqual(apikeys.verify(d, key)["name"], "my script")
        self.assertIsNone(apikeys.verify(d, key + "x"))
        self.assertIsNone(apikeys.verify(d, "aisk_nothing"))
        self.assertIsNone(apikeys.verify(d, "not-a-key"))
        self.assertEqual([k["name"] for k in apikeys.list_keys(d)], ["my script"])
        self.assertNotIn("hash", apikeys.list_keys(d)[0])
        self.assertIsNotNone(apikeys.list_keys(d)[0]["last_used"])
        apikeys.revoke(d, rec["id"])
        self.assertIsNone(apikeys.verify(d, key))
        with self.assertRaises(apikeys.KeyError_):
            apikeys.revoke(d, rec["id"])

    def test_limits(self):
        d = tempfile.mkdtemp()
        for bad in ("", "  ", "x" * 61):
            with self.assertRaises(apikeys.KeyError_):
                apikeys.create(d, bad)
        for i in range(apikeys.MAX_KEYS):
            apikeys.create(d, f"k{i}")
        with self.assertRaises(apikeys.KeyError_):
            apikeys.create(d, "one too many")


@unittest.skipUnless(HAVE, "needs the venv with fastapi + httpx")
class TestKeyRoutes(unittest.TestCase):
    def setUp(self):
        self.app = create_app(tempfile.mkdtemp(), token="tok", static_dir="/nonexistent")
        self.c = TestClient(self.app)
        self.S = {"x-aistudio-token": "tok"}
        self.key = self.c.post("/api/keys", json={"name": "agent"}, headers=self.S).json()["key"]
        self.A = {"x-aistudio-token": self.key}
        self.c.post("/api/projects", json={"name": "demo", "test_pipeline": True}, headers=self.S)
        self.c.put("/api/projects/demo/docs/Story.md", json={"text": MD}, headers=self.S)
        self.c.post("/api/projects/demo/story/convert", headers=self.S)

    def call(self, m, url, h=None, **kw):
        return self.c.request(m.upper(), url, headers=h or self.A, **kw)

    def test_keys_are_managed_by_the_page_only(self):
        self.assertEqual(len(self.call("get", "/api/keys", self.S).json()["keys"]), 1)
        self.assertEqual(self.call("get", "/api/keys").status_code, 403)                          # an agent cannot list keys
        self.assertEqual(self.call("post", "/api/keys", json={"name": "x"}).status_code, 401)     # header-only, session token only
        self.assertEqual(self.c.post("/api/keys?token=tok", json={"name": "x"}).status_code, 401)  # never from a URL
        self.assertEqual(self.call("delete", "/api/keys/abc").status_code, 403)
        kid = self.call("get", "/api/keys", self.S).json()["keys"][0]["id"]
        self.assertEqual(self.call("delete", f"/api/keys/{kid}", self.S).status_code, 200)
        self.assertEqual(self.call("get", "/api/projects").status_code, 401)                      # revoked at once

    def test_an_agent_key_can_do_what_mcp_tools_can(self):
        for m, u in (("get", "/api/projects"), ("get", "/api/projects/demo"), ("get", "/api/projects/demo/docs/Story.md"), ("get", "/api/projects/demo/brief"),
                     ("get", "/api/projects/demo/costs"), ("get", "/api/providers"), ("get", "/api/roles"), ("get", "/api/setup"), ("get", "/api/docs/endpoints")):
            self.assertEqual(self.call(m, u).status_code, 200, u)
        self.assertEqual(self.call("put", "/api/projects/demo/docs/TODO.md", json={"text": "- [ ] x"}).status_code, 200)
        self.assertEqual(self.call("post", "/api/projects", json={"name": "made-by-agent"}).status_code, 200)
        self.assertEqual(self.call("post", "/api/projects/demo/estimate", json={"failure": 0.2}).status_code, 200)
        self.assertEqual(self.c.get("/api/health").status_code, 200)

    def test_an_agent_key_cannot_approve_spend_or_change_settings(self):
        self.call("post", "/api/projects/demo/estimate", self.S, json={"failure": 0.2})
        for m, u, b in (("post", "/api/projects/demo/budget/approve", None), ("post", "/api/projects/demo/proposals/x/approve", {"code": "1"}),
                        ("post", "/api/projects/demo/proposals/x/approve-human", None), ("post", "/api/projects/demo/shots/s01/approve", None),
                        ("delete", "/api/projects/demo", {"confirm": "demo"}), ("get", "/api/projects/demo/export-project", None), ("post", "/api/providers", {"type": "openai"}),
                        ("put", "/api/limits", {"allow_paid": True}), ("put", "/api/roles/chat", {"chain": []}), ("get", "/api/integrations", None),
                        ("post", "/api/projects/demo/chat", {"text": "hi"}), ("put", "/api/projects/demo/edit", {}), ("post", "/api/projects/demo/edit/export", None),
                        ("post", "/api/trash/x/restore", None), ("post", "/api/projects/demo/favorite", {"on": True})):
            r = self.call(m, u, **({"json": b} if b is not None else {}))
            self.assertIn(r.status_code, (401, 403), f"{m} {u} -> {r.status_code}")
        self.assertEqual(self.call("get", "/api/projects/demo", self.S).json()["budget"].get("approved") or False, False)

    def test_a_proposal_from_an_agent_has_no_approval_code(self):
        b = self.call("post", "/api/projects/demo/proposals", json={"kind": "image", "target": "s01"})
        self.assertEqual(b.status_code, 200, b.text)
        self.assertNotIn("code", b.json())
        h = self.call("post", "/api/projects/demo/proposals", self.S, json={"kind": "image", "target": "s01"})
        self.assertEqual(len(h.json()["code"]), 6)                                                # the page still gets it

    def test_bearer_header_and_wrong_keys(self):
        self.assertEqual(self.c.get("/api/projects", headers={"authorization": f"Bearer {self.key}"}).status_code, 200)
        self.assertEqual(self.c.get("/api/projects", headers={"authorization": "Bearer aisk_wrong"}).status_code, 401)
        self.assertEqual(self.c.get("/api/projects").status_code, 401)

    def test_every_route_is_documented_and_the_reference_is_served(self):
        self.assertEqual(api_docs.undocumented(self.app), [])
        eps = self.call("get", "/api/docs/endpoints").json()["endpoints"]
        self.assertGreater(len(eps), 70)
        self.assertTrue(all(e["summary"] and e["group"] in api_docs.GROUPS for e in eps))
        by = {(e["method"], e["path"]): e for e in eps}
        self.assertFalse(by[("POST", "/api/projects/{name}/budget/approve")]["agent"])
        self.assertTrue(by[("POST", "/api/projects/{name}/proposals")]["agent"])

    def test_integrations_describe_the_mcp_server(self):
        j = self.call("get", "/api/integrations", self.S).json()
        self.assertTrue(j["mcp"]["python"] and j["mcp"]["repo"] and j["mcp"]["home"])
        names = {t["name"] for t in j["tools"]}
        self.assertTrue({"propose", "run_proposal", "estimate"} <= names)
        self.assertFalse({"approve", "approve_budget", "set_mode"} & names)


if __name__ == "__main__":
    unittest.main()
