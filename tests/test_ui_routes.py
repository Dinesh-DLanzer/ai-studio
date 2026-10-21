import tests._hermetic as HERM  # noqa: F401
import base64
import tempfile
import unittest
from pathlib import Path

from aistudio import apikeys
from tests.test_flow import logo_bytes

try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    HAVE_API = True
except Exception:  # pragma: no cover
    HAVE_API = False


@unittest.skipUnless(HAVE_API, "fastapi not installed")
class UiRouteTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.c = TestClient(create_app(self.root, token="tok", static_dir="/nonexistent"))
        self.h = {"x-aistudio-token": "tok"}
        _, self.key = apikeys.create(self.root, "agent")
        self.ah = {"x-aistudio-token": self.key}

    def test_formats_and_presets_readable_by_agents(self):
        for path, k in (("/api/formats", "formats"), ("/api/camera-presets", "presets")):
            self.assertTrue(self.c.get(path, headers=self.ah).json()[k])

    def test_brand_kits_and_capabilities_are_human_only(self):
        for method, path in (("get", "/api/brand-kits"), ("post", "/api/brand-kits"), ("put", "/api/brand-kits/x"), ("delete", "/api/brand-kits/x"),
                             ("get", "/api/capabilities"), ("put", "/api/capabilities/p/m"), ("delete", "/api/capabilities/p/m")):
            self.assertEqual(getattr(self.c, method)(path, headers=self.ah).status_code, 403, path)

    def test_kit_lifecycle_and_project_from_format_and_kit(self):
        r = self.c.post("/api/brand-kits", headers=self.h, json={"name": "Acme", "logo_b64": base64.b64encode(logo_bytes()).decode(), "style_words": "bright"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["palette"])
        self.assertEqual(self.c.get("/api/brand-kits/acme/logo", headers=self.h).status_code, 200)
        self.assertEqual(self.c.put("/api/brand-kits/acme", headers=self.h, json={"style_words": "dark"}).json()["style_words"], "dark")
        self.assertEqual(self.c.post("/api/brand-kits", headers=self.h, json={"name": "Acme"}).status_code, 409)
        self.assertEqual(self.c.put("/api/brand-kits/acme", headers=self.h, json={"palette": ["red"]}).status_code, 400)
        r = self.c.post("/api/projects", headers=self.h, json={"name": "reel", "format": "instagram-reel", "brand_kit": "acme"})
        self.assertEqual(r.status_code, 200, r.text)
        p = Path(self.root) / "projects" / "reel"
        self.assertTrue((p / "brand" / "kit.json").is_file())
        self.assertIn("Shot 01", (p / "Story.md").read_text())
        self.assertEqual(self.c.delete("/api/brand-kits/acme", headers=self.h).json(), {"ok": True})
        self.assertTrue((Path(self.root) / "brand_kits" / "_trash").is_dir())
        self.assertEqual(self.c.post("/api/projects", headers=self.h, json={"name": "bad", "format": "nope"}).status_code, 400)

    def test_capability_override_validated(self):
        self.c.post("/api/providers", headers=self.h, json={"type": "fake"})
        r = self.c.put("/api/capabilities/fake/fake-video", headers=self.h, json={"tasks": ["bogus"]})
        self.assertEqual(r.status_code, 400)
        r = self.c.put("/api/capabilities/fake/fake-video", headers=self.h, json={"durations": [4, 8], "frames": {"end": True}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["profile"]["source"], "user")
        self.assertEqual(self.c.delete("/api/capabilities/fake/fake-video", headers=self.h).json(), {"ok": True})
