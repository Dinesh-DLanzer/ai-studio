import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tests._hermetic  # noqa: F401
from aistudio import jobs, youtube
from aistudio.secrets import SecretStore


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.offset = 0

    def request(self, method, url, headers=None, body=None):
        self.calls.append((method, url, headers or {}, body))
        if url.endswith("/token"):
            if (body or {}).get("grant_type") == "refresh_token":
                return {"access_token": "new-access-secret", "refresh_token": "new-refresh-secret", "expires_in": 3600}
            return {"access_token": "access-secret", "refresh_token": "refresh-secret", "expires_in": 3600}
        if "/channels?" in url:
            return {"items": [{"snippet": {"title": "Test Channel"}}]}
        if "uploadType=resumable" in url:
            return {"status": 200, "headers": {"Location": "https://www.googleapis.com/upload/youtube/v3/session-test"}, "body": {}}
        if "session-test" in url:
            rng = (headers or {}).get("Content-Range", "")
            if rng.startswith("bytes */"):
                return {"status": 308, "headers": {"Range": "bytes=0-3"}, "body": {}}
            if rng.startswith("bytes 4-"):
                return {"status": 200, "headers": {}, "body": {"id": "video-123"}}
            raise ConnectionError("interrupted")
        return {"status": 200, "headers": {}, "body": {}}


class YouTubeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = SecretStore(self.root / "secrets")
        self.transport = FakeTransport()

    def test_pkce_authorize_and_state_validation(self):
        pkce = youtube.new_pkce()
        self.assertGreaterEqual(len(pkce["verifier"]), 43)
        self.assertEqual(pkce["challenge"], youtube._b64(hashlib.sha256(pkce["verifier"].encode()).digest()))
        url = youtube.authorize_url({**pkce, "client_id": "client-id"}, "http://127.0.0.1:12345/")
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("redirect_uri=http%3A%2F%2F127.0.0.1%3A12345%2F", url)
        with self.assertRaisesRegex(ValueError, "state"):
            youtube.finish_oauth(self.store, self.transport.request, {"state": "expected"}, "code", "wrong")

    def test_refresh_and_status_never_return_tokens(self):
        self.store.set("youtube", {"client_id": "client", "client_secret": "oauth-secret", "access_token": "old-access-secret",
                                    "refresh_token": "old-refresh-secret", "expires_at": "1"})
        fresh = youtube.valid_tokens(self.store, self.transport.request, now=2)
        self.assertEqual(fresh["access_token"], "new-access-secret")
        status = youtube.status(self.store, self.transport.request)
        self.assertNotIn("access_token", json.dumps(status))
        self.assertNotIn("refresh_token", json.dumps(status))
        self.assertNotIn("client_secret", json.dumps(status))
        self.assertEqual(status["channel_title"], "Test Channel")

    def test_resumable_upload_default_private_and_resume(self):
        project = self.root / "projects" / "demo"
        video = project / "exports" / "youtube" / "platform" / "demo.mp4"
        video.parent.mkdir(parents=True)
        video.write_bytes(b"abcdefghij")
        self.store.set("youtube", {"client_id": "client", "client_secret": "oauth-secret", "access_token": "access-secret",
                                    "refresh_token": "refresh-secret", "expires_at": "9999999999"})
        result = youtube.upload_file(self.store, self.transport.request, video, {"title": "Title", "description": "Desc", "hashtags": ["#tag"]})
        init = next(c for c in self.transport.calls if "uploadType=resumable" in c[1])
        metadata = json.loads(init[3])
        self.assertEqual(metadata["status"]["privacyStatus"], "private")
        self.assertEqual(metadata["snippet"]["tags"], ["tag"])
        self.assertEqual(result["video_id"], "video-123")
        self.assertTrue(any(c[2].get("Content-Range") == "bytes */10" for c in self.transport.calls))

    def test_video_id_survives_optional_thumbnail_failure(self):
        project = self.root / "projects" / "demo"
        video = project / "exports" / "youtube" / "platform" / "demo.mp4"
        video.parent.mkdir(parents=True)
        video.write_bytes(b"video")
        digest = hashlib.sha256(video.read_bytes()).hexdigest()
        (project / "publish.json").write_text(json.dumps({"platform": "youtube", "title": "Changed after confirmation", "description": "", "hashtags": [],
                                                            "thumbnail": "exports/thumbnails/missing.png"}))
        self.store.set("youtube", {"client_id": "client", "client_secret": "oauth-secret", "access_token": "access-secret",
                                    "refresh_token": "refresh-secret", "expires_at": "9999999999"})
        job = {"payload": {"file": "exports/youtube/platform/demo.mp4", "sha256": digest, "privacy": "private", "title": "Title", "tags": [], "category_id": "22", "thumbnail": "exports/thumbnails/missing.png"}}
        result = youtube.upload_job(self.store, project, job, lambda _pct: None, self.transport.request)
        self.assertEqual(result["video_id"], "video-123")
        self.assertIn("thumbnail_error", result)
        upload_meta = next(c for c in self.transport.calls if "uploadType=resumable" in c[1])
        self.assertEqual(json.loads(upload_meta[3])["snippet"]["title"], "Title")

    def test_preview_requires_exported_contained_file_and_preflight(self):
        project = self.root / "projects" / "demo"
        project.mkdir(parents=True)
        (project / "publish.json").write_text(json.dumps({"platform": "youtube", "title": "Title", "status": "exported", "preset_id": "youtube"}))
        out = project / "exports" / "youtube" / "platform" / "demo.mp4"
        out.parent.mkdir(parents=True)
        out.write_bytes(b"video")
        preview = youtube.preview(project, "youtube", preflight=[], channel_title="Test Channel")
        self.assertEqual(preview["sha256"], hashlib.sha256(b"video").hexdigest())
        with self.assertRaisesRegex(ValueError, "preflight"):
            youtube.preview(project, "youtube", preflight=[{"level": "error", "message": "bad"}], channel_title="Test Channel")

    def test_fake_transport_only_enabled_with_all_test(self):
        with patch.dict(os.environ, {"AISTUDIO_FAKE_YOUTUBE": "1", "AISTUDIO_ALL_TEST": "0"}):
            with self.assertRaisesRegex(RuntimeError, "test mode"):
                youtube.transport()

    def test_secrets_are_write_only_and_transport_errors_are_scrubbed(self):
        self.assertEqual(youtube.save_client(self.store, "client-id", "oauth-client-secret"), {"saved": True})
        saved = json.dumps(youtube.status(self.store))
        for secret in ("client-id", "oauth-client-secret", "access_token", "refresh_token"):
            self.assertNotIn(secret, saved)
        self.store.set("youtube", {"client_id": "client-id", "client_secret": "oauth-client-secret", "access_token": "old-access",
                                    "refresh_token": "old-refresh", "expires_at": "9999999999"})
        youtube.save_client(self.store, "new-client", "new-client-secret")
        self.assertFalse(youtube.status(self.store)["connected"])
        self.store.set("youtube", {"client_id": "client-id", "client_secret": "oauth-client-secret",
                                    "access_token": "secret-access-abc", "refresh_token": "secret-refresh-abc", "expires_at": "1"})
        def bad_transport(*_a, **_kw): raise RuntimeError("secret-access-abc in Authorization header")
        with self.assertRaisesRegex(ValueError, "network request failed") as err:
            youtube.valid_tokens(self.store, bad_transport, now=2)
        self.assertNotIn("secret-access-abc", str(err.exception))
        project = self.root / "projects" / "demo"
        project.mkdir(parents=True)
        (project / "publish.json").write_text(json.dumps({"title": "Title", "platform": "youtube"}))
        row = jobs.enqueue(str(self.root), "demo", "publish_upload", payload={"file": "exports/a.mp4", "sha256": "a" * 64, "privacy": "private"})
        serialized = json.dumps(row) + jobs.error_text(err.exception) + (project / "publish.json").read_text()
        self.assertNotIn("secret-access-abc", serialized)
        self.assertNotIn("secret-refresh-abc", serialized)

    def test_title_mismatch_is_refused_before_queue_and_preflight_errors_block(self):
        project = self.root / "projects" / "demo"
        project.mkdir(parents=True)
        (project / "publish.json").write_text(json.dumps({"platform": "youtube", "title": "Title", "status": "exported", "preset_id": "youtube"}))
        class WS:
            secrets = self.store
            def pdir(inner, _project): return project
        class Runner:
            def submit(self, *_a, **_kw): self.fail("must not queue")
        with self.assertRaisesRegex(ValueError, "typed title"):
            youtube.queue_upload(WS(), "demo", "youtube", confirm_title="wrong", preflight=[], runner=Runner())
        with self.assertRaisesRegex(ValueError, "preflight"):
            youtube.preview(project, "youtube", preflight=[{"level": "error"}], channel_title="Test Channel")

    def test_publish_human_only_api_keys_and_title_confirmation(self):
        try:
            from fastapi.testclient import TestClient
            from server.app import create_app
            from aistudio import apikeys
        except Exception as exc:
            self.skipTest(f"FastAPI test client unavailable: {exc}")
        project = self.root / "projects" / "demo"
        project.mkdir(parents=True)
        out = project / "exports" / "youtube" / "platform" / "demo.mp4"
        out.parent.mkdir(parents=True)
        out.write_bytes(b"video")
        (project / "publish.json").write_text(json.dumps({"platform": "youtube", "title": "Title", "status": "exported", "preset_id": "youtube"}))
        _, key = apikeys.create(str(self.root), "agent")
        client = TestClient(create_app(str(self.root), token="human", static_dir="/nonexistent"))
        for method, path, body in (("get", "/api/youtube/status", None), ("put", "/api/youtube/client", {"client_id": "x", "client_secret": "y"}),
                                   ("post", "/api/youtube/connect", {}), ("post", "/api/youtube/disconnect", {}),
                                   ("get", "/api/projects/demo/publish/youtube/preview?preset=youtube", None),
                                   ("post", "/api/projects/demo/publish/youtube", {"confirm_title": "Title"})):
            denied = getattr(client, method)(path, headers={"x-aistudio-token": key}, json=body) if body is not None else getattr(client, method)(path, headers={"x-aistudio-token": key})
            self.assertEqual(denied.status_code, 403, path)
        from aistudio import mcp_server, tool_registry
        self.assertFalse(any("youtube" in name.lower() for name in mcp_server.TOOLS))
        self.assertFalse(any("youtube" in name.lower() for name in tool_registry.crew_tools()))
        with patch("aistudio.youtube.run_preflight", return_value=[]):
            mismatch = client.post("/api/projects/demo/publish/youtube", headers={"x-aistudio-token": "human"}, json={"confirm_title": "Wrong"})
        self.assertEqual(mismatch.status_code, 400)

    def test_upload_kind_is_not_restartable(self):
        job = jobs.enqueue(str(self.root), "demo", "publish_upload", state="running")
        runner = jobs.JobRunner(str(self.root), {"publish_upload": lambda j, progress: self.fail("must not rerun")})
        self.addCleanup(runner.shutdown)
        runner.reconcile()
        self.assertEqual(jobs.get(str(self.root), job["id"])["state"], "needs_sync")


if __name__ == "__main__":
    unittest.main()
