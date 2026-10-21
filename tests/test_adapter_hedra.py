"""Hedra adapter: the requests it makes, the polling, the download, and the failure paths."""
import tempfile
import unittest
from pathlib import Path

from aistudio.providers.adapters.hedra import HedraAdapter
from aistudio.providers.base import AuthError, Rejected, Retryable
from tests._adapter_helpers import FakeTransport

CONN = {"id": "h", "type": "hedra", "secret": {"api_key": "key_123:secret_456"}}
BASE = "https://api.hedra.com"
MODELS = [
    {"slug": "veed-fabric-10", "name": "Veed Fabric 10", "modality": "video"},
    {"slug": "veo-3", "name": "Veo 3", "modality": "video"},
]
JOB_PENDING = {"job_id": "job_abc123", "model": "veed-fabric-10", "status": "PENDING", "outputs": []}
JOB_DONE = {"job_id": "job_abc123", "model": "veed-fabric-10", "status": "COMPLETED",
            "outputs": [{"url": "https://cdn.hedra.com/out.mp4", "asset_id": "asset_123"}]}
JOB_FAILED = {"job_id": "job_abc123", "model": "veed-fabric-10", "status": "FAILED",
              "error": {"message": "generation failed", "code": "INTERNAL"}}


def _file(name, data):
    p = Path(tempfile.mkdtemp()) / name
    p.write_bytes(data)
    return str(p)


def make(*answers):
    t = FakeTransport(*answers)
    return HedraAdapter(CONN, transport=t), t


class TestHedra(unittest.TestCase):
    def test_test_ok_and_auth_header(self):
        a, t = make(MODELS)
        res = a.test()
        self.assertTrue(res["ok"], res)
        self.assertEqual(t.last["method"], "GET")
        self.assertEqual(t.last["url"], BASE + "/v3/models")
        self.assertEqual(t.last["headers"]["Authorization"], "Key key_123:secret_456")

    def test_test_reports_an_auth_error_without_leaking_the_key(self):
        a, t = make(AuthError("HTTP 401: bad key key_123:secret_456"))
        res = a.test()
        self.assertFalse(res["ok"])
        self.assertNotIn("key_123:secret_456", res["message"])
        self.assertIn("401", res["message"])

    def test_list_models(self):
        a, t = make(MODELS)
        models = a.list_models()
        self.assertEqual([m["id"] for m in models], ["veed-fabric-10", "veo-3"])
        self.assertEqual(models[0]["capability"], "video")

    def test_lipsync_submit_uploads_files_and_submits_job(self):
        a, t = make(
            {"url": "https://files.hedra.com/vid_123"},  # video upload
            {"url": "https://files.hedra.com/aud_456"},  # audio upload
            JOB_PENDING,                                  # job submit
        )
        video = _file("shot.mp4", b"VIDEODATA")
        audio = _file("vo.wav", b"AUDIODATA")
        job = a.lipsync_submit("veed-fabric-10", video, audio,
                               {"prompt": "Hello world", "aspect_ratio": "16:9", "resolution": "720p"})
        self.assertEqual(job, {"job_id": "job_abc123", "model": "veed-fabric-10"})
        # Check upload calls
        self.assertEqual(len(t.calls), 3)
        self.assertEqual(t.calls[0]["url"], BASE + "/v3/files")
        self.assertEqual(t.calls[1]["url"], BASE + "/v3/files")
        self.assertEqual(t.calls[2]["url"], BASE + "/v3/models/veed-fabric-10")
        # Check submit body
        submit_body = t.calls[2]["body"]
        self.assertEqual(submit_body["input"]["prompt"], "Hello world")
        self.assertEqual(submit_body["input"]["aspect_ratio"], "16:9")
        self.assertEqual(submit_body["input"]["resolution"], "720p")
        self.assertEqual(submit_body["input"]["start_image"]["source"], "url")
        self.assertEqual(submit_body["input"]["start_image"]["url"], "https://files.hedra.com/vid_123")
        self.assertEqual(submit_body["input"]["audio"]["source"], "url")
        self.assertEqual(submit_body["input"]["audio"]["url"], "https://files.hedra.com/aud_456")

    def test_lipsync_submit_without_key_raises_auth_error(self):
        a, _ = make()
        a._key = None
        with self.assertRaises(AuthError):
            a.lipsync_submit("veed-fabric-10", _file("shot.mp4", b"V"), _file("vo.wav", b"A"))

    def test_lipsync_submit_missing_file_is_rejected(self):
        a, t = make()
        with self.assertRaises(Rejected):
            a.lipsync_submit("veed-fabric-10", "/nope/shot.mp4", _file("vo.wav", b"A"))
        self.assertEqual(t.calls, [])

    def test_lipsync_poll_pending_done_and_failed(self):
        a, t = make(JOB_PENDING, JOB_DONE, JOB_FAILED)
        job = {"job_id": "job_abc123", "model": "veed-fabric-10"}
        self.assertEqual(a.lipsync_poll(job), {"status": "pending", "error": None, "cost": None})
        self.assertEqual(t.last["url"], BASE + "/v3/jobs/job_abc123")
        self.assertEqual(a.lipsync_poll(job), {"status": "done", "error": None, "cost": None})
        self.assertEqual(a.lipsync_poll(job), {"status": "failed", "error": "generation failed", "cost": None})

    def test_lipsync_download_fetches_output_url(self):
        a, t = make(JOB_DONE, b"MP4BYTES")
        data = a.lipsync_download({"job_id": "job_abc123", "model": "veed-fabric-10"})
        self.assertEqual(data, b"MP4BYTES")
        self.assertEqual(t.calls[0]["url"], BASE + "/v3/jobs/job_abc123")
        self.assertEqual(t.calls[1]["url"], "https://cdn.hedra.com/out.mp4")
        self.assertNotIn("Authorization", t.calls[1]["headers"])
        self.assertTrue(t.calls[1]["raw"])

    def test_lipsync_download_before_done_is_retryable(self):
        a, t = make(JOB_PENDING)
        with self.assertRaises(Retryable):
            a.lipsync_download({"job_id": "job_abc123", "model": "veed-fabric-10"})
        self.assertEqual(len(t.calls), 1)

    def test_video_submit_and_poll_download(self):
        """Video generation uses the same job endpoints as lipsync."""
        a, t = make(JOB_PENDING, JOB_PENDING, JOB_DONE, JOB_DONE, b"VIDBYTES")
        job = a.video_submit("veo-3", {"prompt": "A cat", "seconds": 5, "aspect_ratio": "16:9", "resolution": "720p"})
        self.assertEqual(job["job_id"], "job_abc123")
        self.assertEqual(a.video_poll(job), {"status": "pending", "error": None, "cost": None})
        self.assertEqual(a.video_poll(job), {"status": "done", "error": None, "cost": None})
        self.assertEqual(a.video_download(job), b"VIDBYTES")

    def test_provider_type_is_registered(self):
        from aistudio.providers import config as C
        meta = C.PROVIDER_TYPES["hedra"]
        self.assertEqual(meta["label"], "Hedra")
        self.assertEqual(meta["fields"], ["api_key"])
        self.assertFalse(meta["base_url"])
        self.assertIn("lipsync", C.capabilities_of("hedra"))
        self.assertIn("video", C.capabilities_of("hedra"))
        self.assertIs(C.adapter_class("hedra"), HedraAdapter)


if __name__ == "__main__":
    unittest.main()