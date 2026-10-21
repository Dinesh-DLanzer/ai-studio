import tempfile
import unittest

import tests._hermetic  # noqa: F401
from fastapi.testclient import TestClient

from aistudio import project
from server.app import create_app


class TestDocumentHistoryRoutes(unittest.TestCase):
    def setUp(self):
        self.app = create_app(tempfile.mkdtemp(), token="tok", static_dir="/nonexistent")
        self.c = TestClient(self.app)
        self.S = {"x-aistudio-token": "tok"}
        self.c.post("/api/projects", json={"name": "demo", "test_pipeline": True}, headers=self.S)
        self.c.put("/api/projects/demo/docs/Story.md", json={"text": "first story"}, headers=self.S)
        self.c.put("/api/projects/demo/docs/Story.md", json={"text": "second story"}, headers=self.S)
        pdir = self.app.state.ws.pdir("demo")
        project.save_json(pdir, "brief.json", {"title": "first"})
        project.save_json(pdir, "brief.json", {"title": "second"})
        self.key = self.c.post("/api/keys", json={"name": "agent"}, headers=self.S).json()["key"]
        self.A = {"x-aistudio-token": self.key}

    def test_list_read_diff_and_restore_round_trip(self):
        rows = self.c.get("/api/projects/demo/history", params={"doc": "brief.json"}, headers=self.S)
        self.assertEqual(rows.status_code, 200)
        versions = rows.json()["entries"]
        self.assertEqual(len(versions), 1)
        old = versions[0]
        self.assertEqual(set(old), {"ts", "size", "sha"})
        self.assertEqual(len(old["sha"]), 12)

        read = self.c.get(f"/api/projects/demo/history/brief.json/{old['ts']}", headers=self.S)
        self.assertEqual(read.status_code, 200)
        self.assertEqual(read.json(), {"title": "first"})
        diff = self.c.get(f"/api/projects/demo/history/brief.json/{old['ts']}/diff", headers=self.S)
        self.assertEqual(diff.json(), {"added": [], "removed": [], "changed": ["title"]})

        restored = self.c.post(f"/api/projects/demo/history/brief.json/{old['ts']}/restore", headers=self.S)
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()["version"], {"title": "first"})
        self.assertEqual((self.app.state.ws.pdir("demo") / "brief.json").read_text(), '{\n  "title": "first"\n}')
        self.assertEqual((self.app.state.ws.pdir("demo") / "images.json").read_text(), '{\n  "schema_version": 2,\n  "style": "",\n  "images": []\n}')
        after = self.c.get("/api/projects/demo/history", params={"doc": "brief.json"}, headers=self.S).json()["entries"]
        self.assertEqual(len(after), 2)
        self.assertNotEqual(after[0]["sha"], old["sha"])
        self.assertEqual(self.c.get(f"/api/projects/demo/history/brief.json/{after[0]['ts']}", headers=self.S).json(), {"title": "second"})

    def test_markdown_version_is_returned_as_text(self):
        ts = self.c.get("/api/projects/demo/history", params={"doc": "Story.md"}, headers=self.S).json()["entries"][0]["ts"]
        response = self.c.get(f"/api/projects/demo/history/Story.md/{ts}", headers=self.S)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"text": "first story"})

    def test_traversal_and_unknown_docs_are_rejected(self):
        self.assertEqual(self.c.get("/api/projects/demo/history", params={"doc": "../Story.md"}, headers=self.S).status_code, 400)
        for doc, ts in (("../brief.json", "20261021T120000000Z"), ("brief.json", "../secret"), ("brief.json", "20261021T120000000Z.json")):
            response = self.c.get(f"/api/projects/demo/history/{doc}/{ts}", headers=self.S)
            self.assertIn(response.status_code, (400, 404))

    def test_api_keys_cannot_list_read_diff_or_restore(self):
        ts = self.c.get("/api/projects/demo/history", params={"doc": "brief.json"}, headers=self.S).json()["entries"][0]["ts"]
        self.assertEqual(self.c.get("/api/projects/demo/history", params={"doc": "brief.json"}, headers=self.A).status_code, 403)
        for suffix in ("", "/diff"):
            self.assertEqual(self.c.get(f"/api/projects/demo/history/brief.json/{ts}{suffix}", headers=self.A).status_code, 403)
        self.assertEqual(self.c.post(f"/api/projects/demo/history/brief.json/{ts}/restore", headers=self.A).status_code, 403)


if __name__ == "__main__":
    unittest.main()
