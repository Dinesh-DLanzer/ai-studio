import tests._hermetic  # noqa: F401
import json
import os
import tempfile
import unittest
from pathlib import Path

from aistudio.service import Workspace
from aistudio import pairing
try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    from server import api_docs
    HAVE = True
except Exception:
    HAVE = False

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40
MP4 = b"\x00\x00\x00\x18ftypisom" + b"0" * 40
AUDIO = b"ID3" + b"0" * 40


@unittest.skipUnless(HAVE, "fastapi not installed")
class TestNLEBridgeApi(unittest.TestCase):
    def setUp(self):
        tests._hermetic.all_test(self)
        self.root = tempfile.mkdtemp()
        self.session_token = "s" * 32
        os.environ["AISTUDIO_TOKEN"] = self.session_token
        self.ws = Workspace(self.root)
        self.ws.create_project("testproj")
        self.p = self.ws.pdir("testproj")

        # Setup approved clip, stills, and audio
        shots_doc = {
            "aspect_ratio": "9:16",
            "fps": 24,
            "shots": [
                {
                    "id": "s01",
                    "shot": 1,
                    "final_ok": True,
                    "final_clip": "clips/s01_final_a1.mp4",
                    "first_frame": "stills/s01.png",
                    "voiceover": "Welcome to our video presentation.",
                    "seconds": 4,
                },
                {
                    "id": "s02",
                    "shot": 2,
                    "final_ok": False,
                    "final_clip": "clips/s02_unapproved.mp4",
                    "seconds": 3,
                }
            ]
        }
        (self.p / "shots.json").write_text(json.dumps(shots_doc))

        images_doc = {
            "style": "",
            "images": [
                {"id": "hero", "kind": "character", "prompt": "A heroic warrior", "out": "stills/hero.png"}
            ]
        }
        (self.p / "images.json").write_text(json.dumps(images_doc))

        (self.p / "stills").mkdir(exist_ok=True)
        (self.p / "clips").mkdir(exist_ok=True)
        (self.p / "audio").mkdir(exist_ok=True)

        (self.p / "stills" / "hero.png").write_bytes(PNG)
        (self.p / "stills" / "s01.png").write_bytes(PNG)
        (self.p / "clips" / "s01_final_a1.mp4").write_bytes(MP4)
        (self.p / "clips" / "s02_unapproved.mp4").write_bytes(MP4)
        (self.p / "audio" / "background.mp3").write_bytes(AUDIO)

        # Pair a test device
        _, code = pairing.start_pairing(self.root, self.ws.secrets)
        res = pairing.confirm_pairing(self.root, self.ws.secrets, code, "premiere", "Edit Suite")
        self.device_token = res["device_token"]

        # Create an API key
        from aistudio import apikeys
        _, self.api_key = apikeys.create(self.root, "test-agent")

        self.app = create_app(self.root)
        self.c = TestClient(self.app)
        self.human_headers = {"x-aistudio-token": self.session_token}
        self.device_headers = {"authorization": f"Bearer {self.device_token}"}
        self.agent_headers = {"authorization": f"Bearer {self.api_key}"}

    def tearDown(self):
        os.environ.pop("AISTUDIO_TOKEN", None)

    def test_media_route_access_and_filter(self):
        # 1. Human session -> 200
        res = self.c.get("/api/projects/testproj/media?approved=1", headers=self.human_headers)
        self.assertEqual(res.status_code, 200)
        media = res.json().get("media", [])
        kinds = [m["kind"] for m in media]
        self.assertIn("clip", kinds)
        self.assertIn("still", kinds)
        self.assertIn("audio", kinds)

        # Only approved clip (s01) is returned when approved=1
        clip_paths = [m["path"] for m in media if m["kind"] == "clip"]
        self.assertIn("clips/s01_final_a1.mp4", clip_paths)
        self.assertNotIn("clips/s02_unapproved.mp4", clip_paths)

        # Fields required by spec: names, kinds, sizes, sha, relative download paths
        item = media[0]
        self.assertTrue(item.get("name"))
        self.assertTrue(item.get("kind"))
        self.assertIsInstance(item.get("size"), int)
        self.assertTrue(item.get("sha"))
        self.assertTrue(item.get("path"))
        self.assertTrue(item.get("download_path"))

        # 2. Paired device token -> 200
        res_dev = self.c.get("/api/projects/testproj/media?approved=1", headers=self.device_headers)
        self.assertEqual(res_dev.status_code, 200)
        self.assertEqual(len(res_dev.json().get("media", [])), len(media))

        # 3. Plain API key -> 403 Forbidden!
        res_agent = self.c.get("/api/projects/testproj/media?approved=1", headers=self.agent_headers)
        self.assertEqual(res_agent.status_code, 403)

        # 4. Unauthenticated -> 401
        res_unauth = self.c.get("/api/projects/testproj/media?approved=1")
        self.assertEqual(res_unauth.status_code, 401)

    def test_export_aftereffects_jsx_route(self):
        # Human session -> 200
        res = self.c.get("/api/projects/testproj/export/aftereffects.jsx", headers=self.human_headers)
        self.assertEqual(res.status_code, 200)
        jsx = res.text
        self.assertIn("app.beginUndoGroup", jsx)
        self.assertIn("s01_final_a1.mp4", jsx)
        self.assertIn("addComp", jsx)

        # Paired device token -> 200
        res_dev = self.c.get("/api/projects/testproj/export/aftereffects.jsx", headers=self.device_headers)
        self.assertEqual(res_dev.status_code, 200)
        self.assertEqual(res_dev.text, jsx)

        # Plain API key -> 403 Forbidden!
        res_agent = self.c.get("/api/projects/testproj/export/aftereffects.jsx", headers=self.agent_headers)
        self.assertEqual(res_agent.status_code, 403)

    def test_export_fmt_route_reuse(self):
        # Device token can access /api/projects/{name}/export/otio
        res_dev = self.c.get("/api/projects/testproj/export/otio", headers=self.device_headers)
        self.assertEqual(res_dev.status_code, 200)

        # Device token can access /api/projects/{name}/edit/export/otio
        res_edit_dev = self.c.get("/api/projects/testproj/edit/export/otio", headers=self.device_headers)
        self.assertEqual(res_edit_dev.status_code, 200)

        # Plain API key cannot access export routes -> 403
        self.assertEqual(self.c.get("/api/projects/testproj/export/otio", headers=self.agent_headers).status_code, 403)
        self.assertEqual(self.c.get("/api/projects/testproj/edit/export/otio", headers=self.agent_headers).status_code, 403)

    def test_device_token_scope_and_forbidden_routes(self):
        # Allowed routes for device token:
        self.assertEqual(self.c.get("/api/projects", headers=self.device_headers).status_code, 200)
        self.assertEqual(self.c.get("/api/projects/testproj", headers=self.device_headers).status_code, 200)
        self.assertEqual(self.c.get("/files/testproj/stills/hero.png", headers=self.device_headers).status_code, 200)
        self.assertEqual(self.c.get("/api/jobs", headers=self.device_headers).status_code, 200)

        # Proposal creation: allowed for device token, but code is NOT returned
        prop_res = self.c.post("/api/projects/testproj/proposals", headers=self.device_headers, json={
            "kind": "image", "target": "hero"
        })
        self.assertEqual(prop_res.status_code, 200)
        self.assertNotIn("code", prop_res.json())

        # Broad list of forbidden routes for device token -> 403
        forbidden = [
            ("POST", "/api/projects/testproj/proposals/testpid/approve", {"code": "123456"}),
            ("POST", "/api/projects/testproj/proposals/testpid/approve-human", {}),
            ("POST", "/api/projects/testproj/proposals/testpid/reject", {}),
            ("POST", "/api/projects/testproj/shots/s01/approve", {}),
            ("POST", "/api/projects/testproj/budget/approve", {}),
            ("POST", "/api/projects/testproj/batches/b01/approve", {"batch_hash": "h"}),
            ("POST", "/api/projects/testproj/estimate", {"failure": 0.2}),
            ("GET", "/api/library", None),
            ("POST", "/api/library/rebuild", None),
            ("GET", "/api/keys", None),
            ("POST", "/api/keys", {"name": "hack"}),
            ("GET", "/api/providers", None),
            ("POST", "/api/providers", {"type": "google"}),
            ("GET", "/api/projects/testproj/consent", None),
            ("POST", "/api/projects/testproj/consent", {"subject": "Test"}),
            ("GET", "/api/projects/testproj/crew/runs", None),
            ("POST", "/api/projects/testproj/crew/runs", {"agent": "qa", "task": "test"}),
            ("GET", "/api/crew/agents", None),
            ("PUT", "/api/limits", {"ai_cap_usd": 100}),
            ("POST", "/api/pair/start", None),
            ("GET", "/api/pair/devices", None),
            ("DELETE", "/api/pair/devices/dummy", None),
        ]

        for method, path, payload in forbidden:
            if method == "GET":
                r = self.c.get(path, headers=self.device_headers)
            elif method == "POST":
                r = self.c.post(path, headers=self.device_headers, json=payload or {})
            elif method == "PUT":
                r = self.c.put(path, headers=self.device_headers, json=payload or {})
            elif method == "DELETE":
                r = self.c.delete(path, headers=self.device_headers)
            self.assertIn(r.status_code, (401, 403), f"{method} {path} should be 401 or 403 for device token, got {r.status_code}")


if __name__ == "__main__":
    unittest.main()
