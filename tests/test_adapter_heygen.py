"""HeyGen adapter: the requests it makes, the polling, the download, and the failure paths."""
import unittest

from aistudio.providers.adapters.heygen import HeyGenAdapter
from aistudio.providers.base import AuthError, Rejected, Retryable
from tests._adapter_helpers import FakeTransport

CONN = {"id": "hg", "type": "heygen", "secret": {"api_key": "sk-heygen-123456"}}
BASE = "https://api.heygen.com"
LIPSYNC_CREATE_OK = {"data": {"lipsync_id": "ls_abc123"}}
LIPSYNC_PENDING = {"data": {"id": "ls_abc123", "status": "running"}}
LIPSYNC_DONE = {"data": {"id": "ls_abc123", "status": "completed", "video_url": "https://cdn.heygen.com/out.mp4"}}
LIPSYNC_FAILED = {"data": {"id": "ls_abc123", "status": "failed", "failure_message": "no face found"}}
VIDEO_CREATE_OK = {"data": {"video_id": "v_abc123", "status": "waiting"}}
VIDEO_PENDING = {"data": {"id": "v_abc123", "status": "processing"}}
VIDEO_DONE = {"data": {"id": "v_abc123", "status": "completed", "video_url": "https://cdn.heygen.com/vid.mp4"}}
VIDEO_FAILED = {"data": {"id": "v_abc123", "status": "failed", "error_details": "generation failed"}}
USER_ME = {"data": {"username": "test", "email": "test@example.com"}}


def make(*answers):
    t = FakeTransport(*answers)
    return HeyGenAdapter(CONN, transport=t), t


class TestHeyGen(unittest.TestCase):
    def test_test_ok_and_auth_header(self):
        a, t = make(USER_ME)
        res = a.test()
        self.assertTrue(res["ok"], res)
        self.assertEqual(t.last["method"], "GET")
        self.assertEqual(t.last["url"], BASE + "/v3/users/me")
        self.assertEqual(t.last["headers"]["x-api-key"], "sk-heygen-123456")

    def test_test_reports_an_auth_error_without_leaking_the_key(self):
        a, t = make(AuthError("HTTP 401: bad key sk-heygen-123456"))
        res = a.test()
        self.assertFalse(res["ok"])
        self.assertNotIn("sk-heygen-123456", res["message"])
        self.assertIn("401", res["message"])

    def test_list_models(self):
        a, t = make()
        models = a.list_models()
        self.assertEqual([m["id"] for m in models], ["avatar-v3", "avatar-v4", "avatar-v5", "lipsync-speed", "lipsync-precision"])
        self.assertEqual(models[0]["capability"], "video")
        self.assertEqual(models[3]["capability"], "lipsync")

    def test_lipsync_submit(self):
        a, t = make(LIPSYNC_CREATE_OK)
        job = a.lipsync_submit("lipsync-precision", "https://example.com/video.mp4", "https://example.com/audio.mp3",
                               {"title": "My Lipsync"})
        self.assertEqual(job, {"job_id": "ls_abc123", "model": "lipsync-precision"})
        self.assertEqual(t.last["method"], "POST")
        self.assertEqual(t.last["url"], BASE + "/v3/lipsyncs")
        self.assertEqual(t.last["headers"]["x-api-key"], "sk-heygen-123456")
        body = t.last["body"]
        self.assertEqual(body["video"]["type"], "url")
        self.assertEqual(body["video"]["url"], "https://example.com/video.mp4")
        self.assertEqual(body["audio"]["type"], "url")
        self.assertEqual(body["audio"]["url"], "https://example.com/audio.mp3")
        self.assertEqual(body["title"], "My Lipsync")

    def test_lipsync_submit_with_asset_id(self):
        a, t = make(LIPSYNC_CREATE_OK)
        a.lipsync_submit("lipsync-speed", "asset_vid_123", "asset_aud_456")
        body = t.last["body"]
        self.assertEqual(body["video"]["type"], "asset_id")
        self.assertEqual(body["video"]["asset_id"], "asset_vid_123")
        self.assertEqual(body["audio"]["type"], "asset_id")
        self.assertEqual(body["audio"]["asset_id"], "asset_aud_456")

    def test_lipsync_submit_without_key_raises_auth_error(self):
        a, _ = make()
        a._key = None
        with self.assertRaises(AuthError):
            a.lipsync_submit("lipsync-precision", "url", "url")

    def test_lipsync_poll_pending_done_and_failed(self):
        a, t = make(LIPSYNC_PENDING, LIPSYNC_DONE, LIPSYNC_FAILED)
        job = {"job_id": "ls_abc123", "model": "lipsync-precision"}
        self.assertEqual(a.lipsync_poll(job), {"status": "pending", "error": None, "cost": None})
        self.assertEqual(t.last["url"], BASE + "/v3/lipsyncs/ls_abc123")
        self.assertEqual(a.lipsync_poll(job), {"status": "done", "error": None, "cost": None})
        self.assertEqual(a.lipsync_poll(job), {"status": "failed", "error": "no face found", "cost": None})

    def test_lipsync_download_fetches_video_url(self):
        a, t = make(LIPSYNC_DONE, b"MP4BYTES")
        data = a.lipsync_download({"job_id": "ls_abc123", "model": "lipsync-precision"})
        self.assertEqual(data, b"MP4BYTES")
        self.assertEqual(t.calls[0]["url"], BASE + "/v3/lipsyncs/ls_abc123")
        self.assertEqual(t.calls[1]["url"], "https://cdn.heygen.com/out.mp4")
        self.assertNotIn("x-api-key", t.calls[1]["headers"])
        self.assertTrue(t.calls[1]["raw"])

    def test_lipsync_download_before_done_is_retryable(self):
        a, t = make(LIPSYNC_PENDING)
        with self.assertRaises(Retryable):
            a.lipsync_download({"job_id": "ls_abc123", "model": "lipsync-precision"})
        self.assertEqual(len(t.calls), 1)

    def test_video_submit(self):
        a, t = make(VIDEO_CREATE_OK)
        job = a.video_submit("avatar-v4", {
            "prompt": "Hello world",
            "avatar_id": "avatar_123",
            "voice_id": "voice_456",
            "title": "Test Video"
        })
        self.assertEqual(job, {"job_id": "v_abc123", "model": "avatar-v4"})
        self.assertEqual(t.last["method"], "POST")
        self.assertEqual(t.last["url"], BASE + "/v3/videos")
        body = t.last["body"]
        self.assertEqual(body["avatar_id"], "avatar_123")
        self.assertEqual(body["script"], "Hello world")
        self.assertEqual(body["voice_id"], "voice_456")
        self.assertEqual(body["title"], "Test Video")

    def test_video_submit_with_audio_url(self):
        a, t = make(VIDEO_CREATE_OK)
        a.video_submit("avatar-v4", {
            "audio_url": "https://example.com/audio.mp3",
            "image_url": "https://example.com/image.jpg"
        })
        body = t.last["body"]
        self.assertEqual(body["audio_url"], "https://example.com/audio.mp3")
        self.assertEqual(body["image_url"], "https://example.com/image.jpg")
        self.assertNotIn("script", body)

    def test_video_submit_missing_visual_source_raises_rejected(self):
        a, t = make()
        with self.assertRaises(Rejected):
            a.video_submit("avatar-v4", {"prompt": "Hello", "voice_id": "v1"})
        self.assertEqual(t.calls, [])

    def test_video_submit_missing_audio_source_raises_rejected(self):
        a, t = make()
        with self.assertRaises(Rejected):
            a.video_submit("avatar-v4", {"avatar_id": "a1"})
        self.assertEqual(t.calls, [])

    def test_video_poll_pending_done_and_failed(self):
        a, t = make(VIDEO_PENDING, VIDEO_DONE, VIDEO_FAILED)
        job = {"job_id": "v_abc123", "model": "avatar-v4"}
        self.assertEqual(a.video_poll(job), {"status": "pending", "error": None, "cost": None})
        self.assertEqual(t.last["url"], BASE + "/v3/videos/v_abc123")
        self.assertEqual(a.video_poll(job), {"status": "done", "error": None, "cost": None})
        self.assertEqual(a.video_poll(job), {"status": "failed", "error": "generation failed", "cost": None})

    def test_video_download_fetches_video_url(self):
        a, t = make(VIDEO_DONE, b"VIDBYTES")
        data = a.video_download({"job_id": "v_abc123", "model": "avatar-v4"})
        self.assertEqual(data, b"VIDBYTES")
        self.assertEqual(t.calls[0]["url"], BASE + "/v3/videos/v_abc123")
        self.assertEqual(t.calls[1]["url"], "https://cdn.heygen.com/vid.mp4")
        self.assertNotIn("x-api-key", t.calls[1]["headers"])
        self.assertTrue(t.calls[1]["raw"])

    def test_provider_type_is_registered(self):
        from aistudio.providers import config as C
        meta = C.PROVIDER_TYPES["heygen"]
        self.assertEqual(meta["label"], "HeyGen")
        self.assertEqual(meta["fields"], ["api_key"])
        self.assertFalse(meta["base_url"])
        self.assertIn("lipsync", C.capabilities_of("heygen"))
        self.assertIn("video", C.capabilities_of("heygen"))
        self.assertIs(C.adapter_class("heygen"), HeyGenAdapter)


if __name__ == "__main__":
    unittest.main()