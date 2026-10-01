import base64
import unittest
from aistudio.providers.adapters.google import GoogleAdapter
from aistudio.providers.base import Retryable
from tests._adapter_helpers import FakeTransport, png

CONN = {"id": "g", "type": "google", "secret": {"api_key": "AIzaSyTESTKEY1234567890abcdefg"}}
BASE = "https://generativelanguage.googleapis.com/v1beta"
OP = "models/veo-3.1-lite-generate-preview/operations/abc"


def make(*answers):
    t = FakeTransport(*answers)
    return GoogleAdapter(CONN, transport=t), t


def text(t):
    return {"candidates": [{"content": {"parts": [{"text": t}]}}], "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 2}}


class TestGoogle(unittest.TestCase):
    def test_list_models(self):
        a, t = make({"models": [
            {"name": "models/gemini-2.5-flash", "displayName": "Gemini 2.5 Flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-2.5-flash-image", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/veo-3.1", "displayName": "Veo", "supportedGenerationMethods": ["predictLongRunning"]},
            {"name": "models/embed", "supportedGenerationMethods": ["embedContent"]}]})
        got = a.list_models()
        self.assertEqual(t.last["url"], BASE + "/models")
        self.assertEqual(t.last["headers"]["x-goog-api-key"], CONN["secret"]["api_key"])
        self.assertEqual([(m["id"], m["capability"]) for m in got],
                         [("gemini-2.5-flash", "chat"), ("gemini-2.5-flash-image", "image"), ("veo-3.1", "video")])
        self.assertEqual(got[0]["name"], "Gemini 2.5 Flash")

    def test_chat(self):
        a, t = make(text("hi"))
        r = a.chat("gemini-2.5-flash", [{"role": "system", "content": "s1"}, {"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}],
                   {"max_tokens": 20, "temperature": 0.1})
        self.assertEqual(t.last["url"], BASE + "/models/gemini-2.5-flash:generateContent")
        b = t.last["body"]
        self.assertEqual(b["systemInstruction"], {"parts": [{"text": "s1"}]})
        self.assertEqual(b["contents"], [{"role": "user", "parts": [{"text": "q"}]}, {"role": "model", "parts": [{"text": "a"}]}])
        self.assertEqual(b["generationConfig"], {"maxOutputTokens": 20, "temperature": 0.1})
        self.assertEqual(r, {"text": "hi", "usage": {"input": 4, "output": 2}, "cost": None, "model": "gemini-2.5-flash"})

    def test_chat_minimal_body_and_empty(self):
        a, t = make(text("x"), {"candidates": [{"content": {"parts": []}}]})
        a.chat("m", [{"role": "user", "content": "q"}])
        self.assertNotIn("generationConfig", t.last["body"])
        self.assertNotIn("systemInstruction", t.last["body"])
        with self.assertRaises(Retryable):
            a.chat("m", [])

    def test_vision(self):
        a, t = make(text("ok"))
        a.vision("m", "look", [png()])
        parts = t.last["body"]["contents"][0]["parts"]
        self.assertEqual(parts[0], {"text": "look"})
        self.assertEqual(parts[1]["inlineData"]["mimeType"], "image/png")

    def test_image(self):
        data = base64.b64encode(b"PNGOUT").decode()
        a, t = make({"candidates": [{"content": {"parts": [{"text": "here"}, {"inlineData": {"mimeType": "image/png", "data": data}}]}}]},
                    {"candidates": [{"content": {"parts": [{"text": "no image"}]}}]})
        r = a.image("gemini-2.5-flash-image", "a cat", refs=[png()], aspect_ratio="9:16")
        b = t.last["body"]
        self.assertEqual(b["generationConfig"], {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": {"aspectRatio": "9:16"}})
        self.assertEqual(b["contents"][0]["parts"][0], {"text": "a cat"})
        self.assertIn("inlineData", b["contents"][0]["parts"][1])
        self.assertEqual(r["bytes"], b"PNGOUT")
        with self.assertRaises(Retryable):
            a.image("m", "p")

    def test_video_flow(self):
        uri = "https://files/video.mp4?alt=media"
        done = {"done": True, "response": {"generateVideoResponse": {"generatedSamples": [{"video": {"uri": uri}}]}}}
        a, t = make({"name": OP}, {"done": False}, done, done, b"MP4BYTES")
        job = a.video_submit("veo-3.1-lite-generate-preview", {"prompt": "p", "seconds": 4, "resolution": "720p", "aspect_ratio": "9:16", "audio": True, "first_frame": png()})
        self.assertEqual(t.calls[0]["url"], BASE + "/models/veo-3.1-lite-generate-preview:predictLongRunning")
        body = t.calls[0]["body"]
        self.assertEqual(body["parameters"], {"aspectRatio": "9:16", "durationSeconds": 4, "resolution": "720p"})
        self.assertEqual(body["instances"][0]["prompt"], "p")
        self.assertIn("bytesBase64Encoded", body["instances"][0]["image"])
        self.assertEqual(job, {"job_id": OP, "model": "veo-3.1-lite-generate-preview"})
        self.assertEqual(a.video_poll(job)["status"], "pending")
        self.assertEqual(t.last["url"], BASE + "/" + OP)
        self.assertEqual(a.video_poll(job), {"status": "done", "error": None, "cost": None})
        self.assertEqual(a.video_download(job), b"MP4BYTES")
        self.assertEqual(t.last["url"], uri)
        self.assertTrue(t.last["raw"])
        self.assertIn("x-goog-api-key", t.last["headers"])

    def test_video_failed(self):
        a, _ = make({"done": True, "error": {"message": "blocked"}}, {"done": True, "response": {}})
        self.assertEqual(a.video_poll({"job_id": OP, "model": "m"})["error"], "blocked")
        r = a.video_poll({"job_id": OP, "model": "m"})
        self.assertEqual((r["status"], r["error"]), ("failed", "no video in response"))


if __name__ == "__main__":
    unittest.main()
