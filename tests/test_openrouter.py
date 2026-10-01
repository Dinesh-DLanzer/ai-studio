import tests._hermetic  # noqa: F401  (no real key or network in tests)
import base64, tempfile, unittest
from pathlib import Path
from aistudio.providers import openrouter as O

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


class FakeTransport:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, method, path, body=None, raw=False):
        self.calls.append((method, path, body, raw))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class TestOpenRouter(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.img = self.d / "a.png"
        self.img.write_bytes(PNG)

    def test_image(self):
        t = FakeTransport([{"data": [{"b64_json": base64.b64encode(PNG).decode()}], "usage": {"cost": 0.036}}])
        r = O.OpenRouterImage(transport=t).generate("p", [str(self.img)])
        self.assertEqual((r["bytes"], r["cost"], r["model"]), (PNG, 0.036, "qwen/qwen-image-3"))
        m, path, body, _ = t.calls[0]
        self.assertEqual((m, path, body["aspect_ratio"], body["n"]), ("POST", "/images", "9:16", 1))
        self.assertEqual(body["input_references"][0]["type"], "image_url")
        self.assertTrue(body["input_references"][0]["image_url"]["url"].startswith("data:image/png;base64,"))
        with self.assertRaises(ValueError):
            O.OpenRouterImage(transport=t).generate("p", ["x"] * 5)
        with self.assertRaises(O.ProviderError):
            O.OpenRouterImage(transport=FakeTransport([{"data": []}])).generate("p")

    def test_video_ok(self):
        t = FakeTransport([{"id": "j1", "status": "pending"}, {"status": "pending"},
                           {"status": "completed", "usage": {"cost": 0.2}}, b"MP4DATA"])
        v = O.OpenRouterVideo(transport=t, sleep=lambda s: None)
        r = v.generate("p", 4, audio=True, first_frame=str(self.img))
        self.assertEqual((r["bytes"], r["cost"], r["seconds"]), (b"MP4DATA", 0.2, 4))
        body = t.calls[0][2]
        self.assertEqual((body["duration"], body["generate_audio"], body["resolution"]), (4, True, "720p"))
        self.assertEqual(body["frame_images"][0]["frame_type"], "first_frame")
        self.assertEqual(t.calls[-1][1], "/videos/j1/content?index=0")

    def test_video_failed_and_pending(self):
        t = FakeTransport([{"id": "j", "status": "pending"}, {"status": "failed", "error": "moderation", "usage": {"cost": 0.0}}])
        r = O.OpenRouterVideo(transport=t, sleep=lambda s: None).generate("p", 4)
        self.assertEqual((r["error"], r["cost"]), ("moderation", 0.0))
        ticks = iter(range(0, 10000, 400))
        t = FakeTransport([{"id": "j", "status": "pending"}] + [{"status": "pending"}] * 10)
        r = O.OpenRouterVideo(transport=t, sleep=lambda s: None, clock=lambda: next(ticks)).generate("p", 4)
        self.assertEqual((r["pending"], r["job_id"]), (True, "j"))

    def test_video_fetch(self):
        self.assertTrue(O.OpenRouterVideo(transport=FakeTransport([{"status": "pending"}])).fetch("j")["pending"])
        t = FakeTransport([{"status": "completed", "usage": {"cost": 0.3}}, b"X"])
        self.assertEqual(O.OpenRouterVideo(transport=t).fetch("j")["bytes"], b"X")

    def test_vision(self):
        reply = {"choices": [{"message": {"content": 'ok {"verdict":"fail","findings":[{"frame":2,"issue":"extra man","severity":"high"}],"summary":"bad"}'}}],
                 "usage": {"cost": 0.002}}
        t = FakeTransport([reply])
        r = O.OpenRouterVision(transport=t).review([str(self.img)], {"prompt": "check"})
        self.assertEqual((r["verdict"], r["cost"], r["findings"][0]["frame"]), ("fail", 0.002, 2))
        content = t.calls[0][2]["messages"][0]["content"]
        self.assertEqual((content[0]["text"], content[1]["type"]), ("check", "image_url"))

    def test_network_kill_switch(self):
        with self.assertRaises(O.ProviderError) as c:
            O.default_transport()("GET", "/key")
        self.assertIn("AISTUDIO_NO_NETWORK", str(c.exception))

    def test_key_comes_only_from_the_saved_provider_key(self):
        import os
        os.environ["OPENROUTER_API_KEY"] = "sk-or-v1-" + "a" * 60        # an environment variable is NOT a key source any more
        no_net = os.environ.pop("AISTUDIO_NO_NETWORK")
        try:
            with self.assertRaises(O.ProviderError) as c:
                O.default_transport()("GET", "/models")
            self.assertIn("Settings", str(c.exception))
        finally:
            del os.environ["OPENROUTER_API_KEY"]
            os.environ["AISTUDIO_NO_NETWORK"] = no_net


if __name__ == "__main__":
    unittest.main()
