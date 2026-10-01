import tests._hermetic as HERM  # noqa: F401  (no real key or network in tests)
import tempfile, unittest
try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    HAVE = True
except Exception:  # FastAPI not installed in this interpreter
    HAVE = False
from tests.test_story_convert import MD

H = {"x-aistudio-token": "tok"}


@unittest.skipUnless(HAVE, "needs the venv with fastapi + httpx")
class TestServer(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.c = TestClient(create_app(tempfile.mkdtemp(), token="tok", static_dir="/nonexistent"))

    def call(self, m, url, **kw):
        return getattr(self.c, m)(url, headers=H, **kw)

    def test_auth_and_host(self):
        self.assertEqual(self.c.get("/api/health").status_code, 200)
        self.assertEqual(self.c.get("/api/projects").status_code, 401)
        self.assertEqual(self.c.get("/api/projects", headers={"x-aistudio-token": "bad"}).status_code, 401)
        self.assertEqual(self.c.get("/api/projects", headers={"host": "evil.com", **H}).status_code, 403)
        self.assertEqual(self.c.post("/api/projects", json={"name": "x"}, headers={"origin": "https://evil.com", **H}).status_code, 403)

    def test_flow(self):
        self.assertEqual(self.call("post", "/api/projects", json={"name": "demo"}).json(), {"name": "demo"})
        self.call("put", "/api/projects/demo/docs/Story.md", json={"text": MD})
        self.assertEqual(self.call("post", "/api/projects/demo/story/convert").status_code, 200)
        b = self.call("post", "/api/projects/demo/estimate", json={"failure": 0.2}).json()
        self.assertFalse(b["approved"])
        prop = self.call("post", "/api/projects/demo/proposals", json={"kind": "image", "target": "s01"}).json()
        self.assertEqual(len(prop["code"]), 6)
        self.assertEqual(self.call("post", f"/api/projects/demo/proposals/{prop['id']}/approve", json={"code": "x"}).status_code, 400)
        self.call("post", f"/api/projects/demo/proposals/{prop['id']}/approve", json={"code": prop["code"]})
        j = self.call("post", f"/api/projects/demo/proposals/{prop['id']}/execute").json()["job"]
        import time
        for _ in range(50):
            r = self.call("get", f"/api/jobs/{j}").json()
            if r["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(r["status"], "error")              # budget not approved yet
        self.assertIn("budget", r["error"])
        self.call("post", "/api/projects/demo/budget/approve")
        prop = self.call("post", "/api/projects/demo/proposals", json={"kind": "image", "target": "s01"}).json()
        self.call("post", f"/api/projects/demo/proposals/{prop['id']}/approve", json={"code": prop["code"]})
        j = self.call("post", f"/api/projects/demo/proposals/{prop['id']}/execute").json()["job"]
        for _ in range(50):
            r = self.call("get", f"/api/jobs/{j}").json()
            if r["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(r["status"], "done")
        self.assertEqual(self.call("get", "/files/demo/stills/s01.png").status_code, 200)
        self.assertEqual(self.call("get", "/api/projects/demo").json()["costs"]["total"], 0.036)

    def test_file_serving_is_safe(self):
        self.call("post", "/api/projects", json={"name": "demo"})
        for bad in ("../../cost_log.csv", "../demo/brief.md", "brief.md", "%2e%2e/%2e%2e/etc/passwd"):
            self.assertEqual(self.call("get", f"/files/demo/{bad}").status_code, 404, bad)
        self.assertEqual(self.c.get("/files/demo/stills/x.png").status_code, 401)

    def test_rename_languages_ai_and_verify_routes(self):
        self.call("post", "/api/projects", json={"name": "demo"})
        self.call("put", "/api/projects/demo/docs/Story.md", json={"text": MD})
        self.call("post", "/api/projects/demo/story/convert")
        self.assertEqual(self.call("post", "/api/projects/demo/assets/s01/rename", json={"new": "hero"}).status_code, 200)
        self.assertEqual(self.call("post", "/api/projects/demo/assets/s01/rename", json={"new": "hero"}).status_code, 400)
        self.assertEqual(self.call("post", "/api/projects/demo/shots/s01/rename", json={"new": "intro"}).status_code, 200)
        self.assertEqual(self.call("post", "/api/projects/demo/rename", json={"new": "chai"}).json(), {"name": "chai"})
        self.assertEqual(self.call("get", "/api/projects/demo").status_code, 400)            # old name is gone
        self.assertIn("Tamil", [x["name"] for x in self.call("get", "/api/languages").json()["languages"]])
        ai = self.call("get", "/api/ai").json()
        self.assertFalse(ai["settings"]["allow_paid"])
        bad = dict(ai["stored"]); bad["chat"] = {"models": ["openai/gpt-5"]}
        self.assertEqual(self.call("put", "/api/ai", json=bad).status_code, 400)
        self.assertIn("models", self.call("get", "/api/ai/models").json())
        v = self.call("get", "/api/projects/chai/verify").json()
        self.assertEqual(set(v), {"brief", "story", "assets", "shots", "todos"})
        self.assertEqual(self.call("post", "/api/projects/chai/verify", json={"scope": "bogus"}).status_code, 400)
        self.assertEqual(self.call("post", "/api/projects/chai/verify", json={"scope": "shots"}).json(), {"running": True})
        self.assertEqual(self.c.get("/api/ai").status_code, 401)

    def test_mode_and_bad_input(self):
        self.assertEqual(self.call("get", "/api/config").status_code, 404)           # there is no app-wide mode any more
        self.assertEqual(self.call("put", "/api/config/mode", json={"mode": "real"}).status_code, 404)
        self.assertNotIn("mode", self.call("get", "/api/projects").json())
        self.assertEqual(self.call("post", "/api/projects", json={"name": "../x"}).status_code, 400)
        self.assertEqual(self.call("get", "/api/projects/nope").status_code, 400)


if __name__ == "__main__":
    unittest.main()
