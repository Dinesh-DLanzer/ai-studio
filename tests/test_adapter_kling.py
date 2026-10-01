import base64
import hashlib
import hmac
import json
import unittest
from aistudio.providers.adapters.kling import KlingAdapter
from aistudio.providers.base import Rejected, Retryable
from tests._adapter_helpers import FakeTransport, png

CONN = {"id": "k", "type": "kling", "secret": {"access_key": "AK123", "secret_key": "SK456"}}
REQ = {"prompt": "p", "seconds": 5, "resolution": "720p", "aspect_ratio": "9:16", "audio": False, "first_frame": None}
URL = "https://api.klingai.com/v1/videos"


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def make(*answers):
    t = FakeTransport(*answers)
    return KlingAdapter(CONN, transport=t, clock=lambda: 1000.0), t


class TestKling(unittest.TestCase):
    def test_token(self):
        a, _ = make()
        h, p, s = a.make_token().split(".")
        self.assertEqual(json.loads(base64.urlsafe_b64decode(h + "==")), {"alg": "HS256", "typ": "JWT"})
        self.assertEqual(json.loads(base64.urlsafe_b64decode(p + "==")), {"iss": "AK123", "exp": 2800, "nbf": 995})
        self.assertEqual(s, b64u(hmac.new(b"SK456", f"{h}.{p}".encode(), hashlib.sha256).digest()))

    def test_models_and_test(self):
        a, t = make({"code": 0}, {"code": 1001, "message": "bad key"})
        self.assertEqual(a.list_models()[0]["id"], "kling-v1-6")
        self.assertTrue(a.test()["ok"])
        self.assertTrue(t.last["headers"]["Authorization"].startswith("Bearer "))
        self.assertEqual(a.test(), {"ok": False, "message": "bad key"})

    def test_submit(self):
        a, t = make({"code": 0, "data": {"task_id": "T1"}}, {"code": 0, "data": {"task_id": "T2"}}, {"code": 1200, "message": "no"})
        self.assertEqual(a.video_submit("kling-v1-6", REQ), {"job_id": "text2video:T1", "model": "kling-v1-6"})
        self.assertEqual(t.last["url"], URL + "/text2video")
        self.assertEqual(t.last["body"], {"model_name": "kling-v1-6", "prompt": "p", "duration": "5", "aspect_ratio": "9:16", "mode": "std"})
        j = a.video_submit("kling-v1-6", {**REQ, "seconds": 8, "first_frame": png()})
        self.assertEqual(j["job_id"], "image2video:T2")
        self.assertEqual(t.last["body"]["duration"], "10")
        self.assertFalse(t.last["body"]["image"].startswith("data:"))
        with self.assertRaises(Rejected):
            a.video_submit("m", REQ)

    def test_poll_and_download(self):
        job = {"job_id": "text2video:T1", "model": "m"}
        ok = {"code": 0, "data": {"task_status": "succeed", "task_result": {"videos": [{"url": "http://v/1.mp4"}]}}}
        a, t = make({"code": 0, "data": {"task_status": "processing"}}, ok,
                    {"code": 0, "data": {"task_status": "failed", "task_status_msg": "policy"}}, ok, b"MP4", {"code": 0, "data": {"task_status": "submitted"}})
        self.assertEqual(a.video_poll(job)["status"], "pending")
        self.assertEqual(t.last["url"], URL + "/text2video/T1")
        self.assertEqual(a.video_poll(job), {"status": "done", "error": None, "cost": None})
        self.assertEqual(a.video_poll(job), {"status": "failed", "error": "policy", "cost": None})
        self.assertEqual(a.video_download(job), b"MP4")
        self.assertTrue(t.last["raw"])
        with self.assertRaises(Retryable):
            a.video_download(job)


if __name__ == "__main__":
    unittest.main()
