"""Tests for the fal.ai adapter (the queue gateway) with the fake transport."""
import unittest
from aistudio.providers import config as C
from aistudio.providers.adapters.fal import FalAdapter
from aistudio.providers.base import AuthError, Rejected, Retryable
from tests._adapter_helpers import FakeTransport

CONN = {"id": "fl", "type": "fal", "secret": {"api_key": "fal_key_secret_123"}}
QUEUE = "https://queue.fal.run"
PLATFORM = "https://api.fal.ai/v1"
SUBMIT = {"request_id": "req-1",
          "response_url": QUEUE + "/fal-ai/flux/requests/req-1",
          "status_url": QUEUE + "/fal-ai/flux/requests/req-1/status",
          "cancel_url": QUEUE + "/fal-ai/flux/requests/req-1/cancel",
          "queue_position": 0}


def make(*answers):
    t = FakeTransport(*answers)
    return FalAdapter(CONN, transport=t, sleep=lambda s: None), t


def job(model="fal-ai/flux/dev"):
    return {"job_id": "req-1", "model": model, "status_url": SUBMIT["status_url"],
            "response_url": SUBMIT["response_url"]}


class TestFal(unittest.TestCase):
    # -------------------------- registration --------------------------
    def test_registered(self):
        meta = C.PROVIDER_TYPES["fal"]
        self.assertEqual(meta["fields"], ["api_key"])
        self.assertEqual(C.capabilities_of("fal"), ["image", "lipsync", "music", "sfx", "tts", "video"])

    # -------------------------- list_models --------------------------
    def test_list_models_maps_the_capabilities(self):
        a, t = make(
            {"models": [{"endpoint_id": "fal-ai/stable-audio",
                         "metadata": {"display_name": "Stable Audio Open", "category": "text-to-audio",
                                      "tags": ["music"]}},
                        {"endpoint_id": "cassetteai/sound-effects-generator",
                         "metadata": {"category": "text-to-audio", "tags": ["sfx"]}}]},
            {"models": [{"endpoint_id": "fal-ai/qwen-3-tts/text-to-speech/1.7b",
                         "metadata": {"category": "text-to-speech", "tags": ["text-to-speech"]}}]},
            {"models": [{"endpoint_id": "fal-ai/flux/dev",
                         "metadata": {"category": "text-to-image", "tags": []}}]},
            {"models": [{"endpoint_id": "fal-ai/minimax/video-01",
                         "metadata": {"category": "text-to-video", "tags": []}}]},
            {"models": [{"endpoint_id": "fal-ai/sync-lipsync/v3",
                         "metadata": {"category": "video-to-video", "tags": ["lipsync"]}}]},
        )
        caps = {m["id"]: m["capability"] for m in a.list_models()}
        self.assertEqual(caps["fal-ai/stable-audio"], "music")
        self.assertEqual(caps["cassetteai/sound-effects-generator"], "sfx")
        self.assertEqual(caps["fal-ai/qwen-3-tts/text-to-speech/1.7b"], "tts")
        self.assertEqual(caps["fal-ai/flux/dev"], "image")
        self.assertEqual(caps["fal-ai/minimax/video-01"], "video")
        self.assertEqual(caps["fal-ai/sync-lipsync/v3"], "lipsync")
        self.assertEqual(t.calls[0]["url"], PLATFORM + "/models?category=text-to-audio&limit=50&status=active")
        self.assertEqual(t.calls[-1]["url"], PLATFORM + "/models?q=lipsync&limit=50&status=active")
        self.assertEqual(t.calls[0]["headers"]["Authorization"], "Key fal_key_secret_123")

    # -------------------------- test() --------------------------
    def test_test_ok(self):
        a, t = make({"models": [], "has_more": False})
        res = a.test()
        self.assertTrue(res["ok"])
        self.assertEqual(t.last["url"], PLATFORM + "/models?limit=1")

    def test_test_fail_scrubs_the_key(self):
        a, t = make(AuthError("HTTP 401: the key fal_key_secret_123 is not valid"))
        res = a.test()
        self.assertFalse(res["ok"])
        self.assertNotIn("fal_key_secret_123", res["message"])
        self.assertIn("***", res["message"])

    def test_test_without_a_key(self):
        a = FalAdapter({"id": "fl", "type": "fal", "secret": {}}, transport=FakeTransport())
        res = a.test()
        self.assertFalse(res["ok"])
        self.assertIn("no API key", res["message"])

    # -------------------------- submit --------------------------
    def test_submit(self):
        a, t = make(SUBMIT)
        j = a.submit("fal-ai/stable-audio", {"prompt": "jazz", "duration": 30})
        self.assertEqual(t.last["method"], "POST")
        self.assertEqual(t.last["url"], QUEUE + "/fal-ai/stable-audio")
        self.assertEqual(t.last["headers"]["Authorization"], "Key fal_key_secret_123")
        self.assertEqual(t.last["body"], {"prompt": "jazz", "duration": 30})
        self.assertEqual(j["job_id"], "req-1")
        self.assertEqual(j["model"], "fal-ai/stable-audio")
        self.assertEqual(j["status_url"], SUBMIT["status_url"])
        self.assertEqual(j["response_url"], SUBMIT["response_url"])

    def test_submit_needs_owner_and_app(self):
        a, t = make()
        with self.assertRaises(Rejected):
            a.submit("stable-audio", {"prompt": "x"})

    def test_submit_without_a_request_id(self):
        a, t = make({})
        with self.assertRaises(Retryable):
            a.submit("fal-ai/stable-audio", {"prompt": "x"})

    def test_submit_without_a_key(self):
        a = FalAdapter({"id": "fl", "type": "fal", "secret": {}}, transport=FakeTransport())
        with self.assertRaises(AuthError):
            a.submit("fal-ai/stable-audio", {"prompt": "x"})

    # -------------------------- poll --------------------------
    def test_poll(self):
        a, t = make({"status": "IN_QUEUE", "queue_position": 2})
        self.assertEqual(a.poll(job()), {"status": "pending", "error": None, "cost": None})
        self.assertEqual(t.last["url"], SUBMIT["status_url"])
        a, t = make({"status": "IN_PROGRESS", "logs": []})
        self.assertEqual(a.poll(job())["status"], "pending")
        a, t = make({"status": "COMPLETED", "metrics": {"inference_time": 1.5}})
        self.assertEqual(a.poll(job()), {"status": "done", "error": None, "cost": None})
        a, t = make({"status": "COMPLETED", "error": "the model crashed"})
        self.assertEqual(a.poll(job()), {"status": "failed", "error": "the model crashed", "cost": None})

    def test_poll_builds_the_url_from_the_model(self):
        a, t = make({"status": "IN_QUEUE"})
        a.poll({"job_id": "req-9", "model": "fal-ai/sync-lipsync/v3"})
        self.assertEqual(t.last["url"], QUEUE + "/fal-ai/sync-lipsync/requests/req-9/status")

    # -------------------------- result and download --------------------------
    def test_result(self):
        a, t = make({"images": [{"url": "http://cdn/1.png"}], "seed": 42})
        out = a.result(job())
        self.assertEqual(out["images"][0]["url"], "http://cdn/1.png")
        self.assertEqual(t.last["url"], SUBMIT["response_url"])
        self.assertEqual(t.last["headers"]["Authorization"], "Key fal_key_secret_123")

    def test_download(self):
        a, t = make({"audio": {"url": "http://cdn/a.mp3"}}, b"MP3BYTES")
        self.assertEqual(a.download(job()), b"MP3BYTES")
        self.assertEqual(t.last["url"], "http://cdn/a.mp3")
        self.assertNotIn("Authorization", t.last["headers"])

    def test_download_finds_an_image_list(self):
        a, t = make({"images": [{"url": "http://cdn/1.png"}]}, b"PNGBYTES")
        self.assertEqual(a.download(job()), b"PNGBYTES")
        self.assertEqual(t.last["url"], "http://cdn/1.png")

    def test_download_without_media(self):
        a, t = make({"prompt": "x"})
        with self.assertRaises(Retryable):
            a.download(job())

    # -------------------------- generate --------------------------
    def test_generate(self):
        a, t = make(SUBMIT, {"status": "IN_QUEUE"}, {"status": "COMPLETED"},
                    {"audio": {"url": "http://cdn/a.mp3"}}, b"MP3")
        out = a.generate("fal-ai/stable-audio", {"prompt": "jazz"})
        self.assertEqual(out["bytes"], b"MP3")
        self.assertEqual(out["model"], "fal-ai/stable-audio")
        self.assertIsNone(out["cost"])
        self.assertEqual(out["usage"], {})

    def test_generate_failure(self):
        a, t = make(SUBMIT, {"status": "COMPLETED", "error": "boom"})
        with self.assertRaises(Rejected):
            a.generate("fal-ai/stable-audio", {"prompt": "jazz"})

    def test_generate_times_out(self):
        a, t = make(SUBMIT, *[{"status": "IN_QUEUE"}] * 3)
        with self.assertRaises(Retryable):
            a.generate("fal-ai/stable-audio", {"prompt": "jazz"}, {"max_polls": 3})

    # -------------------------- image and video --------------------------
    def test_image(self):
        a, t = make(SUBMIT, {"status": "COMPLETED"}, {"images": [{"url": "http://cdn/i.png"}]}, b"PNG")
        out = a.image("fal-ai/flux/dev", "a cat", aspect_ratio="16:9")
        self.assertEqual(out["bytes"], b"PNG")
        self.assertEqual(t.calls[0]["body"], {"prompt": "a cat", "aspect_ratio": "16:9"})

    def test_video_submit_and_download(self):
        a, t = make(SUBMIT, {"video": {"url": "http://cdn/v.mp4"}}, b"MP4")
        j = a.video_submit("fal-ai/minimax/video-01", {"prompt": "p", "seconds": 5,
                                                        "aspect_ratio": "9:16", "resolution": "720p"})
        self.assertEqual(j["job_id"], "req-1")
        self.assertEqual(t.calls[0]["body"], {"prompt": "p", "duration": 5, "aspect_ratio": "9:16",
                                              "resolution": "720p"})
        self.assertEqual(a.video_download(j), b"MP4")
        self.assertNotIn("Authorization", t.last["headers"])

    # -------------------------- errors --------------------------
    def test_auth_error(self):
        a, t = make(AuthError("HTTP 401"))
        with self.assertRaises(AuthError):
            a.submit("fal-ai/stable-audio", {"prompt": "x"})

    def test_rate_limit(self):
        a, t = make(Retryable("HTTP 429"))
        with self.assertRaises(Retryable):
            a.submit("fal-ai/stable-audio", {"prompt": "x"})

    def test_rejected(self):
        a, t = make(Rejected("HTTP 404: the model does not exist"))
        with self.assertRaises(Rejected):
            a.submit("fal-ai/nope", {"prompt": "x"})

    def test_the_key_is_never_in_the_request_body(self):
        a, t = make(SUBMIT)
        a.submit("fal-ai/stable-audio", {"prompt": "x"})
        self.assertNotIn("fal_key_secret_123", str(t.last["body"]))


if __name__ == "__main__":
    unittest.main()
