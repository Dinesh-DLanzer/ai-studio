import base64
import unittest
from aistudio.providers.adapters.openrouter import OpenRouterAdapter
from aistudio.providers.base import Rejected, Retryable
from tests._adapter_helpers import FakeTransport, png

CONN = {"id": "or", "type": "openrouter", "secret": {"api_key": "sk-or-abcdef123456"}}
BASE = "https://openrouter.ai/api/v1"


def make(*answers):
    t = FakeTransport(*answers)
    return OpenRouterAdapter(CONN, transport=t), t


class TestOpenRouter(unittest.TestCase):
    def test_chat_reports_cost(self):
        a, t = make({"choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 1, "cost": 0.0004}})
        r = a.chat("qwen/x:free", [{"role": "user", "content": "q"}])
        self.assertEqual(t.last["url"], BASE + "/chat/completions")
        self.assertTrue(t.last["body"]["usage"]["include"])
        self.assertEqual(t.last["headers"]["Authorization"], "Bearer sk-or-abcdef123456")
        self.assertEqual(r["cost"], 0.0004)
        with self.assertRaises(Retryable):
            make({"choices": [{"message": {"content": ""}}]})[0].chat("m", [])

    def test_vision(self):
        a, t = make({"choices": [{"message": {"content": "ok"}}]})
        a.vision("google/gemini-2.5-flash-lite", "look", [png()])
        self.assertEqual(t.last["body"]["messages"][0]["content"][1]["type"], "image_url")

    def test_image(self):
        a, t = make({"data": [{"b64_json": base64.b64encode(b"PNG").decode()}], "usage": {"cost": 0.036}})
        r = a.image("qwen/qwen-image-3", "p", refs=[png()])
        self.assertEqual(t.last["url"], BASE + "/images")
        self.assertEqual(t.last["body"]["aspect_ratio"], "9:16")
        self.assertEqual((r["bytes"], r["cost"]), (b"PNG", 0.036))
        with self.assertRaises(Rejected):
            a.image("m", "p", refs=[png()] * 5)

    def test_video(self):
        a, t = make({"id": "J1"}, {"status": "in_progress"}, {"status": "completed", "usage": {"cost": 0.12}}, {"status": "failed", "error": "bad"}, b"MP4")
        job = a.video_submit("google/veo-3.1-lite", {"prompt": "p", "seconds": 4, "resolution": "720p", "aspect_ratio": "9:16", "audio": True, "first_frame": png()})
        self.assertEqual(job, {"job_id": "J1", "model": "google/veo-3.1-lite"})
        self.assertTrue(t.last["body"]["generate_audio"])
        self.assertEqual(t.last["body"]["frame_images"][0]["frame_type"], "first_frame")
        self.assertEqual(a.video_poll(job)["status"], "pending")
        self.assertEqual(a.video_poll(job), {"status": "done", "error": None, "cost": 0.12})
        self.assertEqual(a.video_poll(job)["status"], "failed")
        self.assertEqual(a.video_download(job), b"MP4")
        self.assertEqual(t.last["url"], BASE + "/videos/J1/content?index=0")

    def test_models_and_test(self):
        a, t = make({"data": [{"id": "a/b:free", "name": "AB", "pricing": {"prompt": "0", "completion": "0"}}, {"id": "c/d", "pricing": {"prompt": "0.1", "completion": "0.2"}}]},
                    {"data": {"limit": 10, "limit_remaining": 4.5}})
        m = a.list_models()
        self.assertEqual([x["free"] for x in m], [True, False])
        r = a.test()
        self.assertTrue(r["ok"])
        self.assertIn("$4.50", r["message"])


if __name__ == "__main__":
    unittest.main()
