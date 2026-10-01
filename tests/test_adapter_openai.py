import base64
import unittest
from aistudio.providers.adapters.openai import OpenAIAdapter
from aistudio.providers.base import Retryable, Unsupported, AuthError
from tests._adapter_helpers import FakeTransport, png

CONN = {"id": "o", "type": "openai", "secret": {"api_key": "sk-test-123456"}}


def make(*answers, conn=CONN):
    t = FakeTransport(*answers)
    return OpenAIAdapter(conn, transport=t), t


class TestOpenAI(unittest.TestCase):
    def test_list_models(self):
        a, t = make({"data": [{"id": "gpt-4o"}, {"id": "dall-e-3"}, {"id": "gpt-image-1"}]})
        got = a.list_models()
        self.assertEqual(t.last["method"], "GET")
        self.assertEqual(t.last["url"], "https://api.openai.com/v1/models")
        self.assertEqual(t.last["headers"]["Authorization"], "Bearer sk-test-123456")
        self.assertEqual([(m["id"], m["capability"]) for m in got], [("dall-e-3", "image"), ("gpt-4o", "chat"), ("gpt-image-1", "image")])

    def test_chat(self):
        a, t = make({"choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}})
        r = a.chat("gpt-4o", [{"role": "user", "content": "yo"}], {"max_tokens": 50})
        self.assertEqual(t.last["url"], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(t.last["body"], {"model": "gpt-4o", "messages": [{"role": "user", "content": "yo"}], "max_tokens": 50})
        self.assertEqual(r, {"text": "hi", "usage": {"input": 5, "output": 2}, "cost": None, "model": "gpt-4o"})

    def test_chat_cost_reported_and_custom_base(self):
        conn = {"id": "g", "type": "openai", "base_url": "http://localhost:1234/v1/", "secret": {}}
        a, t = make({"choices": [{"message": {"content": "x"}}], "usage": {"cost": 0.002}}, conn=conn)
        r = a.chat("m", [])
        self.assertEqual(t.last["url"], "http://localhost:1234/v1/chat/completions")
        self.assertNotIn("Authorization", t.last["headers"])
        self.assertEqual(r["cost"], 0.002)

    def test_chat_empty_is_retryable(self):
        a, _ = make({"choices": [{"message": {"content": "  "}}]})
        with self.assertRaises(Retryable):
            a.chat("m", [])

    def test_vision(self):
        a, t = make({"choices": [{"message": {"content": "ok"}}]})
        a.vision("gpt-4o", "what?", [png()])
        c = t.last["body"]["messages"][0]["content"]
        self.assertEqual(c[0], {"type": "text", "text": "what?"})
        self.assertTrue(c[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_image(self):
        b64 = base64.b64encode(b"PNGDATA").decode()
        a, t = make({"data": [{"b64_json": b64}]})
        r = a.image("dall-e-3", "a cat", aspect_ratio="9:16")
        self.assertEqual(t.last["url"], "https://api.openai.com/v1/images/generations")
        self.assertEqual(t.last["body"], {"model": "dall-e-3", "prompt": "a cat", "n": 1, "size": "1024x1536", "response_format": "b64_json"})
        self.assertEqual(r["bytes"], b"PNGDATA")

    def test_image_url_fallback_and_landscape(self):
        a, t = make({"data": [{"url": "http://x/y.png"}]}, b"FROMURL")
        r = a.image("gpt-image-1", "p", aspect_ratio="16:9")
        self.assertEqual(t.calls[0]["body"]["size"], "1536x1024")
        self.assertNotIn("response_format", t.calls[0]["body"])
        self.assertEqual(t.calls[1]["url"], "http://x/y.png")
        self.assertEqual(r["bytes"], b"FROMURL")

    def test_image_refs_unsupported_and_video_unsupported(self):
        a, _ = make()
        with self.assertRaises(Unsupported):
            a.image("gpt-image-1", "p", refs=[png()])
        with self.assertRaises(Unsupported):
            a.video_submit("m", {})

    def test_test_ok_and_failure(self):
        a, _ = make({"data": [{"id": "a"}]})
        self.assertTrue(a.test()["ok"])
        a, _ = make(AuthError("HTTP 401: bad key sk-test-123456"))
        r = a.test()
        self.assertFalse(r["ok"])
        self.assertNotIn("sk-test-123456", r["message"])


if __name__ == "__main__":
    unittest.main()
