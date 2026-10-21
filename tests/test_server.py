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
        shown = self.call("get", "/files/demo/stills/s01.png")
        self.assertEqual(shown.status_code, 200)
        self.assertEqual(shown.headers.get("cache-control"), "no-cache")      # a replaced image must not keep showing its old preview
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


class SecurityAuditFixesTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from fastapi.testclient import TestClient
        from tests import _hermetic  # noqa: F401
        from server.app import create_app
        self.root = tempfile.mkdtemp()
        self.c = TestClient(create_app(self.root, token="human", static_dir="/nonexistent"))
        self.h = {"x-aistudio-token": "human"}

    def test_oauth_callback_never_reflects_markup(self):
        r = self.c.get("/api/providers/chatgpt/oauth/callback", params={"error": "<script>alert(1)</script>"})
        self.assertNotIn("<script>", r.text)
        self.assertIn("&lt;script&gt;", r.text)
        self.assertIn("default-src 'none'", r.headers.get("content-security-policy", ""))

    def test_api_keys_are_refused_in_the_url_but_work_in_a_header(self):
        key = self.c.post("/api/keys", json={"name": "t"}, headers=self.h).json()["key"]
        self.assertEqual(self.c.get("/api/projects", params={"token": key}).status_code, 401)
        self.assertEqual(self.c.get("/api/projects", headers={"x-aistudio-token": key}).status_code, 200)
        self.assertEqual(self.c.get("/api/projects", params={"token": "human"}).status_code, 200)      # the page's own session token may still use the URL (file previews)

    def test_symlinked_project_folders_are_refused(self):
        import os
        from pathlib import Path
        outside = Path(tempfile.mkdtemp())
        (outside / "secret.txt").write_text("x")
        (Path(self.root) / "projects").mkdir(exist_ok=True)
        os.symlink(outside, Path(self.root) / "projects" / "evil")
        self.assertGreaterEqual(self.c.get("/api/projects/evil", headers=self.h).status_code, 400)


class PrintWindowTemplateIsEscapedTests(unittest.TestCase):
    """The storyboard print window is built from project text (titles, prompts, voice lines). Every such value must go through esc()."""

    def test_every_project_derived_interpolation_is_escaped(self):
        import re
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "web" / "src" / "pages" / "StoryDocumentView.tsx").read_text(encoding="utf-8")
        start = src.index("const html = `<!DOCTYPE html>")
        body = src[start: src.index("</html>`;", start)]
        risky = re.findall(r"\$\{(?!esc\()([^}]*\b(?:doc\.|c\.|b\.|s\.|projectName)[^}]*)\}", body)
        # allowed raw interpolations are counts/lengths/conditionals/maps/fileUrl, never user text
        bad = [r for r in risky if not re.search(r"\.length|\.map\(|\.join\(\"\"\)|\?|doc\.shots\.length|frameUrl|fileUrl", r)]
        self.assertEqual(bad, [], f"unescaped project text in the print template: {bad}")
