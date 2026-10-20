"""sync.so (lip sync) adapter: the requests it makes, the polling, the download, and the failure paths."""
import unittest

from aistudio.providers.adapters.sync_so import SyncAdapter
from aistudio.providers.base import AuthError, NotFound, Rejected, Retryable
from tests._adapter_helpers import FakeTransport

CONN = {"id": "s", "type": "sync", "secret": {"api_key": "sk-sync-123456"}}
BASE = "https://api.sync.so"
MODELS = [{"id": "lipsync-2", "name": "Lip Sync 2", "type": "lipsync", "version": "2"},
          {"id": "sync-3", "name": "Sync 3", "type": "lipsync", "version": "3"}]
DONE = {"id": "G1", "status": "COMPLETED", "model": "lipsync-2", "createdAt": "2026-10-20T10:00:00Z",
        "input": [{"type": "video"}, {"type": "audio"}], "outputUrl": "https://cdn.sync.so/out.mp4"}


def make(*answers):
    t = FakeTransport(*answers)
    return SyncAdapter(CONN, transport=t), t


class TestSync(unittest.TestCase):
    def test_test_ok_and_auth_header(self):
        a, t = make(MODELS)
        res = a.test()
        self.assertTrue(res["ok"], res)
        self.assertEqual(t.last["method"], "GET")
        self.assertEqual(t.last["url"], BASE + "/v2/models")
        self.assertEqual(t.last["headers"]["x-api-key"], "sk-sync-123456")

    def test_test_reports_an_auth_error_without_leaking_the_key(self):
        a, t = make(AuthError("HTTP 401: bad key sk-sync-123456"))
        res = a.test()
        self.assertFalse(res["ok"])
        self.assertNotIn("sk-sync-123456", res["message"])
        self.assertIn("401", res["message"])

    def test_list_models(self):
        a, t = make(MODELS)
        models = a.list_models()
        self.assertEqual([m["id"] for m in models], ["lipsync-2", "sync-3"])
        self.assertEqual(models[0]["capability"], "lipsync")

    def test_submit_posts_a_multipart_generation(self):
        a, t = make({"id": "G1", "status": "PENDING", "model": "lipsync-2"})
        video = _file("shot.mp4", b"VIDEODATA")
        audio = _file("vo.wav", b"AUDIODATA")
        job = a.lipsync_submit("lipsync-2", video, audio, {"sync_mode": "cut_off", "output_file_name": "shot_1"})
        self.assertEqual(job, {"job_id": "G1", "model": "lipsync-2"})
        self.assertEqual(t.last["method"], "POST")
        self.assertEqual(t.last["url"], BASE + "/v2/generate")
        self.assertEqual(t.last["headers"]["x-api-key"], "sk-sync-123456")
        self.assertTrue(t.last["headers"]["Content-Type"].startswith("multipart/form-data; boundary="))
        body = t.last["body"]
        self.assertIsInstance(body, bytes)
        self.assertIn(b'name="model"', body)
        self.assertIn(b"lipsync-2", body)
        self.assertIn(b'name="options"', body)
        self.assertIn(b"cut_off", body)
        self.assertIn(b'name="outputFileName"', body)
        self.assertIn(b'name="video"; filename="shot.mp4"', body)
        self.assertIn(b"VIDEODATA", body)
        self.assertIn(b'name="audio"; filename="vo.wav"', body)
        self.assertIn(b"AUDIODATA", body)

    def test_submit_defaults_the_sync_mode(self):
        a, t = make({"id": "G1", "status": "PENDING"})
        a.lipsync_submit("lipsync-2", _file("s.mp4", b"V"), _file("a.wav", b"A"))
        self.assertIn(b'"sync_mode": "cut_off"', t.last["body"])

    def test_submit_without_an_id_is_retryable(self):
        a, _ = make({"status": "PENDING"})
        with self.assertRaises(Retryable):
            a.lipsync_submit("lipsync-2", _file("s.mp4", b"V"), _file("a.wav", b"A"))

    def test_submit_failures_propagate(self):
        a, _ = make(AuthError("HTTP 401: Unauthorized"))
        with self.assertRaises(AuthError):
            a.lipsync_submit("lipsync-2", _file("s.mp4", b"V"), _file("a.wav", b"A"))
        a, _ = make(Rejected("HTTP 422: generation_input_validation_failed"))
        with self.assertRaises(Rejected):
            a.lipsync_submit("lipsync-2", _file("s.mp4", b"V"), _file("a.wav", b"A"))
        a, _ = make(NotFound("HTTP 404: generation_not_found"))
        with self.assertRaises(NotFound):
            a.lipsync_submit("lipsync-2", _file("s.mp4", b"V"), _file("a.wav", b"A"))

    def test_submit_with_a_missing_file_is_rejected(self):
        a, t = make()
        with self.assertRaises(Rejected):
            a.lipsync_submit("lipsync-2", "/nope/shot.mp4", _file("a.wav", b"A"))
        self.assertEqual(t.calls, [])

    def test_poll_pending_done_and_failed(self):
        a, t = make({"id": "G1", "status": "PENDING"}, DONE,
                    {"id": "G1", "status": "FAILED", "error": "no face found", "errorCode": "generation_failed"})
        job = {"job_id": "G1", "model": "lipsync-2"}
        self.assertEqual(a.lipsync_poll(job), {"status": "pending", "error": None, "cost": None})
        self.assertEqual(t.last["url"], BASE + "/v2/generate/G1")
        self.assertEqual(a.lipsync_poll(job), {"status": "done", "error": None, "cost": None})
        self.assertEqual(a.lipsync_poll(job), {"status": "failed", "error": "no face found", "cost": None})

    def test_poll_rejected_uses_the_error_code(self):
        a, _ = make({"id": "G1", "status": "REJECTED", "errorCode": "generation_input_validation_failed"})
        res = a.lipsync_poll({"job_id": "G1", "model": "lipsync-2"})
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["error"], "generation_input_validation_failed")

    def test_download_fetches_the_signed_url_without_the_key(self):
        a, t = make(DONE, b"https://cdn.sync.so/signed/out.mp4", b"MP4BYTES")
        data = a.lipsync_download({"job_id": "G1", "model": "lipsync-2"})
        self.assertEqual(data, b"MP4BYTES")
        self.assertEqual(t.calls[0]["url"], BASE + "/v2/generate/G1")
        self.assertEqual(t.calls[1]["url"], BASE + "/v2/generations/G1/download")
        self.assertEqual(t.calls[1]["headers"]["x-api-key"], "sk-sync-123456")
        self.assertEqual(t.calls[2]["url"], "https://cdn.sync.so/signed/out.mp4")
        self.assertNotIn("x-api-key", t.calls[2]["headers"])
        self.assertTrue(t.calls[2]["raw"])

    def test_download_before_the_job_is_done_is_retryable(self):
        a, t = make({"id": "G1", "status": "PROCESSING"})
        with self.assertRaises(Retryable):
            a.lipsync_download({"job_id": "G1", "model": "lipsync-2"})
        self.assertEqual(len(t.calls), 1)


def _file(name, data):
    import tempfile
    from pathlib import Path
    p = Path(tempfile.mkdtemp()) / name
    p.write_bytes(data)
    return str(p)


if __name__ == "__main__":
    unittest.main()
