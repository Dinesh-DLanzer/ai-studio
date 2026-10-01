import unittest
from aistudio.providers.adapters.runway import RunwayAdapter
from aistudio.providers.base import AuthError, Retryable
from tests._adapter_helpers import FakeTransport, png

CONN = {"id": "r", "type": "runway", "secret": {"api_key": "key_runway_secret_value"}}
BASE = "https://api.dev.runwayml.com/v1"
REQ = {"prompt": "p", "seconds": 5, "resolution": "720p", "aspect_ratio": "9:16", "audio": False, "first_frame": None}


def make(*answers):
    t = FakeTransport(*answers)
    return RunwayAdapter(CONN, transport=t), t


class TestRunway(unittest.TestCase):
    def test_models_and_test(self):
        a, t = make({"credit": 1})
        self.assertEqual([m["id"] for m in a.list_models()], ["gen4_turbo", "gen3a_turbo"])
        self.assertTrue(a.test()["ok"])
        self.assertEqual(t.last["url"], BASE + "/organization")
        self.assertEqual(t.last["headers"]["Authorization"], "Bearer key_runway_secret_value")
        self.assertEqual(t.last["headers"]["X-Runway-Version"], "2024-11-06")
        a, _ = make(AuthError("HTTP 401: key_runway_secret_value bad"))
        r = a.test()
        self.assertFalse(r["ok"])
        self.assertNotIn("key_runway_secret_value", r["message"])

    def test_submit_text_and_image(self):
        a, t = make({"id": "task1"}, {"id": "task2"})
        self.assertEqual(a.video_submit("gen4_turbo", REQ), {"job_id": "task1", "model": "gen4_turbo"})
        self.assertEqual(t.last["url"], BASE + "/text_to_video")
        self.assertEqual(t.last["body"], {"model": "gen4_turbo", "promptText": "p", "ratio": "720:1280", "duration": 5})
        a.video_submit("gen4_turbo", {**REQ, "first_frame": png(), "aspect_ratio": "16:9"})
        self.assertEqual(t.last["url"], BASE + "/image_to_video")
        self.assertTrue(t.last["body"]["promptImage"].startswith("data:image/png;base64,"))
        self.assertEqual(t.last["body"]["ratio"], "1280:720")

    def test_poll(self):
        a, t = make({"status": "RUNNING"}, {"status": "SUCCEEDED", "output": ["http://x/v.mp4"]}, {"status": "FAILED", "failure": "nsfw"})
        job = {"job_id": "t1", "model": "m"}
        self.assertEqual(a.video_poll(job)["status"], "pending")
        self.assertEqual(t.last["url"], BASE + "/tasks/t1")
        self.assertEqual(a.video_poll(job), {"status": "done", "error": None, "cost": None})
        self.assertEqual(a.video_poll(job), {"status": "failed", "error": "nsfw", "cost": None})

    def test_download(self):
        a, t = make({"status": "SUCCEEDED", "output": ["http://x/v.mp4"]}, b"VIDEO", {"status": "RUNNING"})
        job = {"job_id": "t1", "model": "m"}
        self.assertEqual(a.video_download(job), b"VIDEO")
        self.assertEqual(t.last["url"], "http://x/v.mp4")
        self.assertTrue(t.last["raw"])
        self.assertNotIn("Authorization", t.last["headers"])
        with self.assertRaises(Retryable):
            a.video_download(job)


if __name__ == "__main__":
    unittest.main()
