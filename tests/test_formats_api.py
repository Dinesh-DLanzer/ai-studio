"""The HTTP surface of formats and brand kits (plan 19).

Formats are static catalog data: an API key may read them.  Brand kits hold logos and brand
look: only a human session may read or write them.  Creating a project may name a format and
a brand kit; an unknown id is a 400 and leaves no project behind.
"""
import base64
import json
import tempfile
import unittest
from pathlib import Path

import tests._hermetic as HERM  # noqa: F401  (no real key or network in tests)
from aistudio import apikeys
from server import api_docs

try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    HAVE_API = True
except Exception:  # pragma: no cover
    HAVE_API = False

from tests.test_flow import logo_bytes


@unittest.skipUnless(HAVE_API, "needs the venv with fastapi + httpx")
class TestFormatsApi(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.root = tempfile.mkdtemp()
        self.c = TestClient(create_app(self.root, token="tok", static_dir="/nonexistent"))
        self.h = {"x-aistudio-token": "tok"}
        _, self.key = apikeys.create(self.root, "agent")
        self.ah = {"x-aistudio-token": self.key}

    def call(self, method, url, **kw):
        return getattr(self.c, method)(url, headers=self.h, **kw)

    # ---------------------------------------------------------------- formats
    def test_formats_are_static_data_an_api_key_may_read(self):
        r = self.c.get("/api/formats", headers=self.ah)
        self.assertEqual(r.status_code, 200)
        ids = [f["id"] for f in r.json()["formats"]]
        self.assertIn("instagram-reel", ids)
        self.assertIn("product-ad", ids)
        for f in r.json()["formats"]:
            self.assertTrue(f["label"] and f["aspect_ratio"] and f["notes"])

    def test_unknown_format_is_a_400_and_leaves_no_project(self):
        r = self.call("post", "/api/projects", json={"name": "bad", "format": "nope"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse((Path(self.root) / "projects" / "bad").exists())

    def test_unknown_brand_kit_is_a_400_and_leaves_no_project(self):
        r = self.call("post", "/api/projects", json={"name": "bad", "brand_kit": "nope"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse((Path(self.root) / "projects" / "bad").exists())

    def test_project_from_a_format_and_a_kit(self):
        kit = self.call("post", "/api/brand-kits", json={"name": "Acme", "style_words": "clean, bright",
                                                          "logo_b64": base64.b64encode(logo_bytes()).decode()})
        self.assertEqual(kit.status_code, 200, kit.text)
        r = self.call("post", "/api/projects", json={"name": "reel", "format": "instagram-reel", "brand_kit": "acme"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"name": "reel"})
        p = Path(self.root) / "projects" / "reel"
        shots = json.loads((p / "shots.json").read_text(encoding="utf-8"))
        self.assertEqual(shots["format"], "instagram-reel")
        self.assertEqual(shots["aspect_ratio"], "9:16")
        self.assertEqual(shots["brand_kit"], "acme")
        self.assertTrue((p / "brand" / "kit.json").is_file())
        self.assertIn("Shot 01", (p / "Story.md").read_text(encoding="utf-8"))

    def test_a_blank_project_is_unchanged(self):
        r = self.call("post", "/api/projects", json={"name": "plain"})
        self.assertEqual(r.status_code, 200)
        p = Path(self.root) / "projects" / "plain"
        shots = json.loads((p / "shots.json").read_text(encoding="utf-8"))
        self.assertEqual(shots["aspect_ratio"], "9:16")
        self.assertEqual(shots["audio"], False)
        self.assertNotIn("format", shots)
        self.assertNotIn("brand_kit", shots)
        self.assertFalse((p / "edit.json").exists())
        self.assertFalse((p / "brand").exists())

    # ---------------------------------------------------------------- brand kits
    def test_brand_kits_are_human_session_only(self):
        self.call("post", "/api/brand-kits", json={"name": "Acme"})
        for method, path, body in (("get", "/api/brand-kits", None),
                                    ("post", "/api/brand-kits", {"name": "Other"}),
                                    ("get", "/api/brand-kits/acme", None),
                                    ("put", "/api/brand-kits/acme", {"style_words": "x"}),
                                    ("delete", "/api/brand-kits/acme", None),
                                    ("get", "/api/brand-kits/acme/logo", None)):
            r = getattr(self.c, method)(path, headers=self.ah, **({"json": body} if body is not None else {}))
            self.assertEqual(r.status_code, 403, path)

    def test_the_handler_refuses_an_api_key_even_if_the_doc_were_wrong(self):
        """agent=False in the docs is the first gate; the handler checks again (defence in depth)."""
        doc = api_docs.DOCS["GET /api/brand-kits"]
        old = doc["agent"]
        doc["agent"] = True
        try:
            self.assertEqual(self.c.get("/api/brand-kits", headers=self.ah).status_code, 403)
        finally:
            doc["agent"] = old

    def test_a_human_session_manages_the_kits(self):
        r = self.call("post", "/api/brand-kits", json={"name": "Acme"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["id"], "acme")
        self.assertEqual([k["id"] for k in self.call("get", "/api/brand-kits").json()["kits"]], ["acme"])
        self.assertEqual(self.call("put", "/api/brand-kits/acme", json={"style_words": "dark"}).json()["style_words"], "dark")
        self.assertEqual(self.call("delete", "/api/brand-kits/acme").json(), {"ok": True})
        self.assertTrue((Path(self.root) / "brand_kits" / "_trash" / "acme").is_dir())


if __name__ == "__main__":
    unittest.main()
