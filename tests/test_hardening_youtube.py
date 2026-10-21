import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import tests._hermetic as HERM
from aistudio import consent, jobs, youtube
from aistudio.domain.common import ServiceError, _sha
from server.app import create_app


class FakeSecretStore:
    def __init__(self):
        self.data = {
            "youtube": {
                "client_id": "test-client",
                "client_secret": "test-secret",
                "access_token": "test-token",
                "refresh_token": "test-refresh",
                "expires_at": "9999999999",
            }
        }

    def get(self, key):
        return self.data.get(key, {})

    def set(self, key, val):
        self.data[key] = val

    def delete(self, key):
        self.data.pop(key, None)


class TestHardeningYouTube(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.patch_env = patch.dict("os.environ", {"AISTUDIO_FAKE_YOUTUBE": "1", "AISTUDIO_ALL_TEST": "1"})
        self.patch_env.start()
        self.addCleanup(self.patch_env.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "projects" / "demo"
        self.project.mkdir(parents=True)
        self.store = FakeSecretStore()

        # Create dummy export file and metadata
        self.export_dir = self.project / "exports" / "youtube" / "platform"
        self.export_dir.mkdir(parents=True)
        self.video_file = self.export_dir / "demo.mp4"
        self.video_bytes = b"MP4-VIDEO-PAYLOAD-FOR-TEST"
        self.video_file.write_bytes(self.video_bytes)
        consent.write_lineage(self.project, self.video_file, {"editor_render": True}, kind="editor_render")
        self.video_sha = hashlib.sha256(self.video_bytes).hexdigest()

        # Create thumbnail
        from io import BytesIO
        from PIL import Image
        self.thumb_dir = self.project / "exports" / "thumbnails"
        self.thumb_dir.mkdir(parents=True)
        self.thumb_file = self.thumb_dir / "thumb.png"
        image = BytesIO()
        Image.new("RGB", (2, 2), "red").save(image, format="PNG")
        self.thumb_bytes = image.getvalue()
        self.thumb_file.write_bytes(self.thumb_bytes)
        consent.write_lineage(self.project, self.thumb_file, {"tool": "thumbnail_extract"}, source_sha="test-source-sha", kind="thumbnail_extract")
        self.thumb_sha = hashlib.sha256(self.thumb_bytes).hexdigest()
        HERM.register_test_media(self.project, "exports/youtube/platform/demo.mp4", "exports/thumbnails/thumb.png")

        self.publish_doc = {
            "platform": "youtube",
            "title": "My Great Video",
            "description": "Video description",
            "status": "exported",
            "preset_id": "youtube",
            "thumbnail": "exports/thumbnails/thumb.png",
        }
        (self.project / "publish.json").write_text(json.dumps(self.publish_doc), encoding="utf-8")

        self.runner = jobs.JobRunner(str(self.root), {})

        class WS:
            secrets = self.store
            def pdir(inner, _name): return self.project

        self.ws = WS()

    def tearDown(self):
        if hasattr(self, "runner"):
            self.runner.shutdown()
            self.runner.pool.shutdown(wait=True)
        try:
            self.tmp.cleanup()
        except Exception:
            import shutil
            shutil.rmtree(self.tmp.name, ignore_errors=True)

    def test_post_mismatch_refused_on_sha256_title_or_privacy(self):
        # 1. SHA256 mismatch in queue_upload
        with self.assertRaisesRegex(ValueError, "sha256"):
            youtube.queue_upload(
                self.ws, "demo", "youtube",
                privacy="private", confirm_title="My Great Video",
                preflight=[], runner=self.runner,
                sha256="wrong-sha256", title="My Great Video"
            )

        # 2. Title mismatch in queue_upload
        with self.assertRaisesRegex(ValueError, "title"):
            youtube.queue_upload(
                self.ws, "demo", "youtube",
                privacy="private", confirm_title="My Great Video",
                preflight=[], runner=self.runner,
                sha256=self.video_sha, title="Wrong Title"
            )

        # 3. HTTP POST endpoint enforces sha256, title, and privacy
        client = TestClient(create_app(str(self.root), token="human", static_dir="/nonexistent"))
        url = "/api/projects/demo/publish/youtube"
        headers = {"x-aistudio-token": "human"}

        with patch("aistudio.youtube.run_preflight", return_value=[]), patch("aistudio.youtube.status", return_value={"connected": True, "channel_title": "AI Studio Test Channel"}):
            # Missing sha256 -> 400
            res = client.post(url, headers=headers, json={"preset": "youtube", "title": "My Great Video", "privacy": "private"})
            self.assertEqual(res.status_code, 400)

            # Mismatched sha256 -> 400
            res = client.post(url, headers=headers, json={"preset": "youtube", "sha256": "0"*64, "title": "My Great Video", "privacy": "private"})
            self.assertEqual(res.status_code, 400)

            # Mismatched title -> 400
            res = client.post(url, headers=headers, json={"preset": "youtube", "sha256": self.video_sha, "title": "Wrong Title", "privacy": "private"})
            self.assertEqual(res.status_code, 400)

            # Invalid privacy -> 400
            res = client.post(url, headers=headers, json={"preset": "youtube", "sha256": self.video_sha, "title": "My Great Video", "privacy": "secret"})
            self.assertEqual(res.status_code, 400)

            # Correct previewed values -> 200
            res = client.post(url, headers=headers, json={"preset": "youtube", "sha256": self.video_sha, "title": "My Great Video", "privacy": "private"})
            self.assertEqual(res.status_code, 200)

    def test_queue_upload_requires_title_and_sha_at_function_boundary(self):
        for kwargs in ({"confirm_title": "", "sha256": self.video_sha},
                       {"confirm_title": "My Great Video", "sha256": ""}):
            with self.assertRaises(ValueError):
                youtube.queue_upload(self.ws, "demo", "youtube", preflight=[], runner=self.runner, **kwargs)

    def test_named_thumbnail_must_be_readable_supported_and_hashable(self):
        self.thumb_file.unlink()
        with self.assertRaisesRegex(ValueError, "thumbnail"):
            youtube.preview(self.project, "youtube", preflight=[], channel_title="AI Studio Test Channel")
        self.thumb_file.write_bytes(self.thumb_bytes)
        bad = self.project / "exports" / "thumbnails" / "thumb.gif"
        bad.write_bytes(b"gif")
        doc = dict(self.publish_doc, thumbnail="exports/thumbnails/thumb.gif")
        (self.project / "publish.json").write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "thumbnail"):
            youtube.preview(self.project, "youtube", preflight=[], channel_title="AI Studio Test Channel")

    def test_upload_job_requires_thumbnail_digest_before_video_upload(self):
        prev = youtube.preview(self.project, "youtube", preflight=[], channel_title="AI Studio Test Channel")
        prev.pop("thumbnail_sha256")
        calls = []
        with self.assertRaisesRegex(ValueError, "thumbnail"):
            youtube.upload_job(self.store, self.project, {"payload": prev}, lambda _pct: None,
                               call=lambda *a, **kw: calls.append(a))
        self.assertEqual(calls, [])

    def test_freeze_thumbnail_sha_at_queue_time_and_refuse_if_changed(self):
        # Preview includes thumbnail_sha256
        prev = youtube.preview(self.project, "youtube", preflight=[], channel_title="AI Studio Test Channel")
        self.assertEqual(prev["thumbnail_sha256"], self.thumb_sha)

        # Queue upload captures thumbnail_sha256
        res = youtube.queue_upload(
            self.ws, "demo", "youtube",
            privacy="private", confirm_title="My Great Video",
            preflight=[], runner=self.runner,
            sha256=self.video_sha, title="My Great Video"
        )
        job = jobs.get(str(self.root), res["job"])
        self.assertEqual(job["payload"]["thumbnail_sha256"], self.thumb_sha)

        # Tamper thumbnail on disk
        self.thumb_file.write_bytes(b"\x89PNG-TAMPERED-THUMBNAIL")

        # upload_job detects tampering
        calls = []
        def fake_call(method, url, headers=None, body=None):
            calls.append((method, url))
            return youtube.fake_transport(method, url, headers=headers, body=body)

        with self.assertRaisesRegex(ValueError, "thumbnail changed"):
            youtube.upload_job(self.store, self.project, job, lambda _pct: None, call=fake_call)

    def test_preview_refuses_unverified_video_before_upload(self):
        (self.project / "consent.json").write_text("[]", encoding="utf-8")
        self.video_file.with_name(self.video_file.name + ".meta.json").unlink()
        with self.assertRaisesRegex(ServiceError, "unverified"):
            youtube.preview(self.project, "youtube", channel_title="test channel")

    def test_preview_refuses_missing_or_invalid_thumbnail(self):
        self.thumb_file.unlink()
        with self.assertRaisesRegex(ValueError, "thumbnail"):
            youtube.preview(self.project, "youtube", channel_title="test channel")
        self.thumb_file.write_bytes(b"not a png")
        with self.assertRaisesRegex(ValueError, "PNG or JPEG"):
            youtube.preview(self.project, "youtube", channel_title="test channel")

    def test_stream_hash_and_upload_exact_handle(self):
        # Restore valid thumbnail
        self.thumb_file.write_bytes(self.thumb_bytes)
        prev = youtube.preview(self.project, "youtube", preflight=[], channel_title="AI Studio Test Channel")
        job = {"payload": prev}

        uploaded_handles = []
        orig_upload_file = youtube.upload_file
        def spy_upload_file(secret_store, call, path, metadata, privacy="private", progress=None, file_size=None, filename=None):
            uploaded_handles.append(path)
            return orig_upload_file(secret_store, call, path, metadata, privacy=privacy, progress=progress, file_size=file_size, filename=filename)

        with patch("aistudio.youtube.upload_file", side_effect=spy_upload_file):
            res = youtube.upload_job(self.store, self.project, job, lambda _pct: None, call=youtube.fake_transport)
            self.assertEqual(res["video_id"], "test-video-id")

        # Verify that an open file handle was passed, not just a Path
        self.assertEqual(len(uploaded_handles), 1)
        self.assertTrue(hasattr(uploaded_handles[0], "read"))

    def test_consent_enforced_for_real_person_timelines_and_assets(self):
        # 1. Asset marked real_person in images.json
        images_doc = {
            "style": "",
            "images": [
                {"id": "spokesperson", "kind": "character", "out": "stills/spokesperson.png", "real_person": True, "subject": "Sam"}
            ]
        }
        (self.project / "images.json").write_text(json.dumps(images_doc), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "consent required"):
            youtube.preview(self.project, "youtube", preflight=[], channel_title="AI Studio Test Channel")

        with self.assertRaisesRegex(ValueError, "consent required"):
            youtube.queue_upload(
                self.ws, "demo", "youtube",
                privacy="private", confirm_title="My Great Video",
                preflight=[], runner=self.runner,
                sha256=self.video_sha, title="My Great Video"
            )

        # Record consent for Sam -> passes
        consent.record(self.project, "Sam", "I consent")
        prev = youtube.preview(self.project, "youtube", preflight=[], channel_title="AI Studio Test Channel")
        self.assertTrue(prev["sha256"])

        # 2. Timeline references a clip whose sha is marked real_person
        clip_file = self.project / "clips" / "scene1.mp4"
        clip_file.parent.mkdir(parents=True, exist_ok=True)
        clip_file.write_bytes(b"ACTOR-CLIP-BYTES")
        HERM.register_test_media(self.project, "clips/scene1.mp4")
        clip_sha = _sha(clip_file)
        consent.mark_real_person(self.project, "scene1", clip_sha, "Actor Alex")

        edit_doc = {
            "tracks": {
                "video": [
                    {"id": "t1", "src": "clips/scene1.mp4"}
                ]
            }
        }
        (self.project / "edit.json").write_text(json.dumps(edit_doc), encoding="utf-8")

        # Now preview/queue fails because clip_sha is unconsented
        with self.assertRaisesRegex(ValueError, "consent required"):
            youtube.preview(self.project, "youtube", preflight=[], channel_title="AI Studio Test Channel")

        # Record sha-bound consent for Actor Alex -> passes
        consent.record(self.project, "Actor Alex", "I consent", sha=clip_sha)
        prev2 = youtube.preview(self.project, "youtube", preflight=[], channel_title="AI Studio Test Channel")
        self.assertTrue(prev2["sha256"])

    def test_dead_urllib_branch_removed(self):
        # Test that _urllib_transport accepts list body without error
        with patch("urllib.request.urlopen") as mock_urlopen:
            class MockResponse:
                status = 200
                headers = {}
                def read(self): return b'{"ok": true}'
                def __enter__(self): return self
                def __exit__(self, *args): pass
            mock_urlopen.return_value = MockResponse()
            resp = youtube._urllib_transport("POST", "http://example.com", body=[{"item": 1}])
            self.assertEqual(resp["status"], 200)
            self.assertEqual(resp["body"], {"ok": True})


if __name__ == "__main__":
    unittest.main()
