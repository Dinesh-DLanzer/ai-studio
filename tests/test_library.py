import csv
import json
import tempfile
import time
import unittest
from pathlib import Path

from aistudio import library, store


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.project = self.root / "projects" / "demo"
        (self.project / "stills").mkdir(parents=True)
        (self.project / "clips" / "_discarded").mkdir(parents=True)
        (self.project / "stills" / "hero.png").write_bytes(b"image")
        (self.project / "stills" / "hero.png.meta.json").write_text(json.dumps({"prompt": "red hero", "model": "fake/image", "provider": "fake", "seed": 7, "params": {"size": "small"}, "category": "character"}))
        (self.project / "clips" / "_discarded" / "old.mp4").write_bytes(b"clip")
        with (self.project / "cost_log.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["timestamp", "shot", "stage", "model", "cost", "result", "provider", "attempt", "prompt"])
            w.writeheader()
            w.writerow({"timestamp": "100", "shot": "hero", "stage": "image", "model": "fake/image", "cost": "0.2", "result": "ok", "provider": "fake", "attempt": "1", "prompt": "red hero"})
            w.writerow({"timestamp": "101", "shot": "bad", "stage": "clip", "model": "fake/video", "cost": "0", "result": "failed: nope", "provider": "fake", "attempt": "1", "prompt": "failed attempt"})

    def tearDown(self):
        store.close_all()

    def test_rebuild_metadata_cost_rows_and_idempotency(self):
        rows = library.rebuild(self.root)
        self.assertGreaterEqual(len(rows), 2)
        self.assertTrue(any(r["status"] == "failed" for r in rows))
        hero = next(r for r in rows if r["file"] == "stills/hero.png")
        self.assertEqual((hero["prompt"], hero["model"], hero["category"]), ("red hero", "fake/image", "character"))
        self.assertEqual(len(library.rebuild(self.root)), len(rows))

    def test_search_filters_and_favorite(self):
        library.rebuild(self.root)
        self.assertTrue(library.search(self.root, "hero")["items"])
        row = library.search(self.root, "", {"failed": True})["items"][0]
        library.set_favorite(self.root, row["id"], True)
        self.assertTrue(library.get(self.root, row["id"])["favorite"])
        self.assertEqual(len(library.search(self.root, "", {"favorite": True})["items"]), 1)

    def test_like_fallback_when_fts_is_unavailable(self):
        library.rebuild(self.root)
        original = library._ensure_fts
        library._ensure_fts = lambda root: False
        try:
            self.assertTrue(library.search(self.root, "hero")["items"])
        finally:
            library._ensure_fts = original

    def test_incremental_promote_use_and_remix(self):
        row = library.index_output(self.root, "demo", "stills/hero.png")
        self.assertIsNotNone(row)
        promoted = library.promote(self.root, "demo", "stills/hero.png")
        target = library.use_in_project(self.root, promoted["id"], "demo", "image")
        self.assertTrue((self.project / target["file"]).exists())
        req = library.remix(self.root, row["id"], "demo")
        self.assertEqual(req["kind"], "image")
        self.assertFalse((self.project / "proposals.json").exists())

    def test_refuses_traversal_and_10k_smoke(self):
        with self.assertRaises((ValueError, FileNotFoundError)):
            library.promote(self.root, "demo", "../outside")
        start = time.monotonic()
        for i in range(10000):
            p = self.project / "stills" / f"i{i}.png"
            p.touch()
        library.rebuild(self.root)
        self.assertLess(time.monotonic() - start, 45)      # a smoke bound against quadratic blow-ups, not a benchmark (slow machines vary)

    def test_crew_excludes_library_search(self):
        from aistudio import tool_registry
        self.assertNotIn("search_library", tool_registry.crew_tools())

    def test_api_keys_can_read_but_cannot_write(self):
        try:
            from fastapi.testclient import TestClient
            from server.app import create_app
        except ImportError:
            self.skipTest("FastAPI test client unavailable")
        client = TestClient(create_app(str(self.root), token="human", static_dir="/nonexistent"))
        human = {"x-aistudio-token": "human"}
        agent = {"x-aistudio-token": client.post("/api/keys", json={"name": "test"}, headers=human).json()["key"]}
        self.assertEqual(client.get("/api/library", headers=human).status_code, 200)
        self.assertEqual(client.get("/api/library", headers=agent).status_code, 403)         # cross-project data: human session only, like MCP and the crew
        self.assertEqual(client.get("/api/library/x", headers=agent).status_code, 403)
        for method, url, body in (("post", "/api/library/rebuild", {}), ("post", "/api/library/promote", {"project": "demo", "file": "stills/hero.png"}),
                                  ("post", "/api/library/use", {"id": "x", "project": "demo", "kind": "image"}),
                                  ("post", "/api/library/remix", {"id": "x", "project": "demo"}),
                                  ("post", "/api/library/x/favorite", {"on": True})):
            self.assertEqual(getattr(client, method)(url, json=body, headers=agent).status_code, 403, url)


class LibraryConsentAndAccessTests(unittest.TestCase):
    def setUp(self):
        import json
        from tests import _hermetic  # noqa: F401
        from aistudio.service import Workspace
        self.root = Path(tempfile.mkdtemp())
        self.ws = Workspace(self.root)
        self.ws.create_project("a")
        self.ws.create_project("b")
        self.pa, self.pb = self.ws.pdir("a"), self.ws.pdir("b")
        (self.pa / "stills").mkdir(exist_ok=True)
        (self.pa / "stills" / "maya.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 20)
        (self.pa / "stills" / "maya.png.meta.json").write_text(json.dumps({"real_person": True, "subject": "Maya", "prompt": "p"}))

    def test_promote_and_use_need_a_human_recorded_consent(self):
        from aistudio import consent, library
        with self.assertRaises(Exception):
            library.promote(self.root, "a", "stills/maya.png")
        consent.record(self.pa, "Maya", "I agree", kind="real_person")
        item = library.promote(self.root, "a", "stills/maya.png")
        with self.assertRaises(Exception):
            library.use_in_project(self.root, item["id"], "b", "image")      # the TARGET project needs its own consent
        consent.record(self.pb, "Maya", "I agree", kind="real_person")
        self.assertTrue(library.use_in_project(self.root, item["id"], "b", "image"))

    def test_a_hand_written_consent_dict_no_longer_approves_anything(self):
        import json
        from aistudio import library
        (self.pa / "consent.json").write_text(json.dumps({"real_person": True}))
        with self.assertRaises(Exception):
            library.promote(self.root, "a", "stills/maya.png")

    def test_rebuild_without_a_projects_folder_returns_empty(self):
        from aistudio import library
        self.assertEqual(library.rebuild(tempfile.mkdtemp()), [])
