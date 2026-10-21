"""Tavus adapter: the requests it makes, the polling, the download, and the failure paths."""
import unittest

from aistudio.providers.adapters.tavus import TavusAdapter
from aistudio.providers.base import AuthError, Rejected, Retryable
from tests._adapter_helpers import FakeTransport

CONN = {"id": "tv", "type": "tavus", "secret": {"api_key": "sk-tavus-123456"}}
BASE = "https://tavusapi.com"
VIDEO_CREATE_OK = {"video_id": "vid_abc123", "status": "queued", "video_name": "Test", "hosted_url": "https://tavus.video/vid_abc123"}
VIDEO_PENDING = {"video_id": "vid_abc123", "status": "generating"}
VIDEO_DONE = {"video_id": "vid_abc123", "status": "ready", "download_url": "https://cdn.tavus.io/vid_abc123.mp4", "hosted_url": "https://tavus.video/vid_abc123"}
VIDEO_FAILED = {"video_id": "vid_abc123", "status": "error", "error_details": "generation failed"}
FACES = [{"face_id": "face_123", "face_name": "Test Face"}]


def make(*answers):
    t = FakeTransport(*answers)
    return TavusAdapter(CONN, transport=t), t


class TestTavus(unittest.TestCase):
    def test_test_ok_and_auth_header(self):
        a, t = make(FACES)
        res = a.test()
        self.assertTrue(res["ok"], res)
        self.assertEqual(t.last["method"], "GET")
        self.assertEqual(t.last["url"], BASE + "/v2/faces")
        self.assertEqual(t.last["headers"]["x-api-key"], "sk-tavus-123456")

    def test_test_reports_an_auth_error_without_leaking_the_key(self):
        a, t = make(AuthError("HTTP 401: bad key sk-tavus-123456"))
        res = a.test()
        self.assertFalse(res["ok"])
        self.assertNotIn("sk-tavus-123456", res["message"])
        self.assertIn("401", res["message"])

    def test_list_models(self):
        a, t = make()
        models = a.list_models()
        self.assertEqual([m["id"] for m in models], ["phoenix-4.5", "phoenix-4", "phoenix-3"])
        self.assertEqual(models[0]["capability"], "video")

    def test_lipsync_submit_requires_face_id_and_audio_url(self):
        a, t = make(VIDEO_CREATE_OK)
        job = a.lipsync_submit("phoenix-4.5", "face_123", "https://example.com/audio.mp3",
                               {"video_name": "My LipSync"})
        self.assertEqual(job, {"job_id": "vid_abc123", "model": "phoenix-4.5"})
        self.assertEqual(t.last["method"], "POST")
        self.assertEqual(t.last["url"], BASE + "/v2/videos")
        self.assertEqual(t.last["headers"]["x-api-key"], "sk-tavus-123456")
        body = t.last["body"]
        self.assertEqual(body["replica_id"], "face_123")
        self.assertEqual(body["audio_url"], "https://example.com/audio.mp3")
        self.assertEqual(body["video_name"], "My LipSync")

    def test_lipsync_submit_missing_face_id_raises_rejected(self):
        a, t = make()
        with self.assertRaises(Rejected):
            a.lipsync_submit("phoenix-4.5", "", "https://example.com/audio.mp3")
        self.assertEqual(t.calls, [])

    def test_lipsync_submit_missing_audio_url_raises_rejected(self):
        a, t = make()
        with self.assertRaises(Rejected):
            a.lipsync_submit("phoenix-4.5", "face_123", "")
        self.assertEqual(t.calls, [])

    def test_lipsync_submit_without_key_raises_auth_error(self):
        a, _ = make()
        a._key = None
        with self.assertRaises(AuthError):
            a.lipsync_submit("phoenix-4.5", "face_123", "https://example.com/audio.mp3")

    def test_lipsync_poll_pending_done_and_failed(self):
        a, t = make(VIDEO_PENDING, VIDEO_DONE, VIDEO_FAILED)
        job = {"job_id": "vid_abc123", "model": "phoenix-4.5"}
        self.assertEqual(a.lipsync_poll(job), {"status": "pending", "error": None, "cost": None})
        self.assertEqual(t.last["url"], BASE + "/v2/videos/vid_abc123")
        self.assertEqual(a.lipsync_poll(job), {"status": "done", "error": None, "cost": None})
        self.assertEqual(a.lipsync_poll(job), {"status": "failed", "error": "generation failed", "cost": None})

    def test_lipsync_download_fetches_download_url(self):
        a, t = make(VIDEO_DONE, b"MP4BYTES")
        data = a.lipsync_download({"job_id": "vid_abc123", "model": "phoenix-4.5"})
        self.assertEqual(data, b"MP4BYTES")
        self.assertEqual(t.calls[0]["url"], BASE + "/v2/videos/vid_abc123")
        self.assertEqual(t.calls[1]["url"], "https://cdn.tavus.io/vid_abc123.mp4")
        self.assertNotIn("x-api-key", t.calls[1]["headers"])
        self.assertTrue(t.calls[1]["raw"])

    def test_lipsync_download_uses_hosted_url_if_no_download_url(self):
        # Test fallback to hosted_url
        a, t = make({"video_id": "vid_abc123", "status": "ready", "hosted_url": "https://tavus.video/vid_abc123"}, b"MP4BYTES")
        data = a.lipsync_download({"job_id": "vid_abc123", "model": "phoenix-4.5"})
        self.assertEqual(data, b"MP4BYTES")
        self.assertEqual(t.calls[1]["url"], "https://tavus.video/vid_abc123")

    def test_lipsync_download_before_done_is_retryable(self):
        a, t = make(VIDEO_PENDING)
        with self.assertRaises(Retryable):
            a.lipsync_download({"job_id": "vid_abc123", "model": "phoenix-4.5"})
        self.assertEqual(len(t.calls), 1)

    def test_video_submit_with_script(self):
        a, t = make(VIDEO_CREATE_OK)
        job = a.video_submit("phoenix-4.5", {
            "prompt": "Hello world",
            "face_id": "face_123",
            "video_name": "Test Video"
        })
        self.assertEqual(job, {"job_id": "vid_abc123", "model": "phoenix-4.5"})
        body = t.last["body"]
        self.assertEqual(body["replica_id"], "face_123")
        self.assertEqual(body["script"], "Hello world")
        self.assertEqual(body["video_name"], "Test Video")

    def test_video_submit_with_audio_url(self):
        a, t = make(VIDEO_CREATE_OK)
        a.video_submit("phoenix-4.5", {
            "audio_url": "https://example.com/audio.mp3",
            "replica_id": "face_456"
        })
        body = t.last["body"]
        self.assertEqual(body["audio_url"], "https://example.com/audio.mp3")
        self.assertEqual(body["replica_id"], "face_456")
        self.assertNotIn("script", body)

    def test_video_submit_missing_face_id_raises_rejected(self):
        a, t = make()
        with self.assertRaises(Rejected):
            a.video_submit("phoenix-4.5", {"prompt": "Hello"})
        self.assertEqual(t.calls, [])

    def test_video_submit_missing_script_and_audio_raises_rejected(self):
        a, t = make()
        with self.assertRaises(Rejected):
            a.video_submit("phoenix-4.5", {"face_id": "face_123"})
        self.assertEqual(t.calls, [])

    def test_video_poll_and_download(self):
        """Video uses same endpoints as lipsync."""
        a, t = make(VIDEO_PENDING, VIDEO_PENDING, VIDEO_DONE, VIDEO_DONE, b"VIDBYTES")
        job = a.video_submit("phoenix-4.5", {"prompt": "Hello", "face_id": "face_123"})
        self.assertEqual(a.video_poll(job), {"status": "pending", "error": None, "cost": None})
        self.assertEqual(a.video_poll(job), {"status": "done", "error": None, "cost": None})
        self.assertEqual(a.video_download(job), b"VIDBYTES")

    def test_provider_type_is_registered(self):
        from aistudio.providers import config as C
        meta = C.PROVIDER_TYPES["tavus"]
        self.assertEqual(meta["label"], "Tavus")
        self.assertEqual(meta["fields"], ["api_key"])
        self.assertFalse(meta["base_url"])
        self.assertIn("lipsync", C.capabilities_of("tavus"))
        self.assertIn("video", C.capabilities_of("tavus"))
        self.assertIs(C.adapter_class("tavus"), TavusAdapter)


if __name__ == "__main__":
    unittest.main()