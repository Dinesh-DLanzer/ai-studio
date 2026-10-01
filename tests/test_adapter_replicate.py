import unittest
from aistudio.providers.adapters.replicate import ReplicateAdapter
from aistudio.providers.base import Rejected, Retryable
from tests._adapter_helpers import FakeTransport, png

CONN = {"id": "rp", "type": "replicate", "secret": {"api_key": "r8_secretvalue123"}}
BASE = "https://api.replicate.com/v1"
REQ = {"prompt": "p", "seconds": 6, "resolution": "720p", "aspect_ratio": "9:16", "audio": False, "first_frame": None}


def make(*answers):
    t = FakeTransport(*answers)
    return ReplicateAdapter(CONN, transport=t, sleep=lambda s: None), t


class TestReplicate(unittest.TestCase):
    def test_models_and_test(self):
        a, t = make({"type": "user"})
        self.assertEqual({m["capability"] for m in a.list_models()}, {"image", "video"})
        self.assertTrue(a.test()["ok"])
        self.assertEqual(t.last["url"], BASE + "/account")
        self.assertEqual(t.last["headers"]["Authorization"], "Bearer r8_secretvalue123")

    def test_video_submit(self):
        a, t = make({"id": "P1"}, {"id": "P2"})
        self.assertEqual(a.video_submit("minimax/video-01", REQ), {"job_id": "P1", "model": "minimax/video-01"})
        self.assertEqual(t.last["url"], BASE + "/models/minimax/video-01/predictions")
        self.assertEqual(t.last["body"], {"input": {"prompt": "p", "duration": 6, "aspect_ratio": "9:16"}})
        a.video_submit("m/x", {**REQ, "first_frame": png(), "input_extra": {"seed": 1}})
        i = t.last["body"]["input"]
        self.assertTrue(i["first_frame_image"].startswith("data:image/png"))
        self.assertEqual(i["seed"], 1)

    def test_poll_download(self):
        job = {"job_id": "P1", "model": "m/x"}
        a, t = make({"status": "processing"}, {"status": "succeeded"}, {"status": "failed", "error": "oom"},
                    {"status": "succeeded", "output": ["http://o/1.mp4"]}, b"MP4", {"status": "starting"})
        self.assertEqual(a.video_poll(job)["status"], "pending")
        self.assertEqual(t.last["url"], BASE + "/predictions/P1")
        self.assertEqual(a.video_poll(job), {"status": "done", "error": None, "cost": None})
        self.assertEqual(a.video_poll(job), {"status": "failed", "error": "oom", "cost": None})
        self.assertEqual(a.video_download(job), b"MP4")
        self.assertNotIn("Authorization", t.last["headers"])
        with self.assertRaises(Retryable):
            a.video_download(job)

    def test_image(self):
        a, t = make({"id": "P9"}, {"status": "processing"}, {"status": "succeeded", "output": "http://o/i.png"}, b"PNG")
        r = a.image("black-forest-labs/flux-1.1-pro", "cat", refs=[png()])
        self.assertEqual(t.calls[0]["body"]["input"]["aspect_ratio"], "9:16")
        self.assertIn("image", t.calls[0]["body"]["input"])
        self.assertEqual(r["bytes"], b"PNG")

    def test_image_failure_and_timeout(self):
        a, _ = make({"id": "P9"}, {"status": "failed", "error": "bad"})
        with self.assertRaises(Rejected):
            a.image("m/x", "p")
        a, _ = make({"id": "P9"}, *[{"status": "processing"}] * 3)
        with self.assertRaises(Retryable):
            a.image("m/x", "p", opts={"max_polls": 3})


if __name__ == "__main__":
    unittest.main()
