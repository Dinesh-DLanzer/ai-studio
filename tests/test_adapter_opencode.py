import unittest
from aistudio.providers.adapters.opencode import OpenCodeAdapter
from aistudio.providers.base import Retryable, Unsupported
from tests._adapter_helpers import FakeTransport, png

CONN = {"id": "oc", "type": "opencode", "secret": {"api_key": "oc-key-123456"}}
BASE = "https://opencode.ai/inference"


def make(*answers, conn=CONN):
    t = FakeTransport(*answers)
    return OpenCodeAdapter(conn, transport=t), t


class TestOpenCodeAdapter(unittest.TestCase):
    def test_list_models(self):
        a, t = make({"data": [
            {"id": "mimo-v2.6-flash-free", "name": "MiMo Free"},
            {"id": "kimi-k2.6", "name": "Kimi K2.6"},
            {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6"},
        ]})
        models = a.list_models()
        self.assertEqual(t.last["url"], f"{BASE}/v1/models")
        self.assertEqual(t.last["headers"]["Authorization"], "Bearer oc-key-123456")
        self.assertEqual(len(models), 3)
        free_flags = {m["id"]: m["free"] for m in models}
        self.assertTrue(free_flags["mimo-v2.6-flash-free"])
        self.assertFalse(free_flags["kimi-k2.6"])

    def test_test_connection(self):
        a, _ = make({"data": [{"id": "kimi-k2.6"}]})
        res = a.test()
        self.assertTrue(res["ok"])
        self.assertIn("Connected successfully", res["message"])

    def test_chat_openai_protocol(self):
        a, t = make({"choices": [{"message": {"content": "Hello from Kimi"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        res = a.chat("kimi-k2.6", [{"role": "user", "content": "Hi"}], {"temperature": 0.7})
        self.assertEqual(t.last["url"], f"{BASE}/openai/v1/chat/completions")
        self.assertEqual(t.last["body"]["model"], "kimi-k2.6")
        self.assertEqual(t.last["body"]["temperature"], 0.7)
        self.assertEqual(res["text"], "Hello from Kimi")
        self.assertEqual(res["usage"], {"input": 10, "output": 5})

    def test_chat_anthropic_protocol(self):
        a, t = make({
            "content": [{"type": "text", "text": "Hello from Claude"}],
            "usage": {"input_tokens": 12, "output_tokens": 8},
        })
        res = a.chat(
            "claude-sonnet-4-6",
            [{"role": "system", "content": "You are helpful"}, {"role": "user", "content": "Hello"}],
            {"max_tokens": 2048},
        )
        self.assertEqual(t.last["url"], f"{BASE}/anthropic/v1/messages")
        self.assertEqual(t.last["body"]["model"], "claude-sonnet-4-6")
        self.assertEqual(t.last["body"]["system"], "You are helpful")
        self.assertEqual(t.last["body"]["messages"], [{"role": "user", "content": "Hello"}])
        self.assertEqual(t.last["body"]["max_tokens"], 2048)
        self.assertEqual(res["text"], "Hello from Claude")
        self.assertEqual(res["usage"], {"input": 12, "output": 8})

    def test_chat_gemini_protocol(self):
        a, t = make({
            "candidates": [{"content": {"parts": [{"text": "Hello from Gemini"}]}}],
            "usageMetadata": {"promptTokenCount": 15, "candidatesTokenCount": 7},
        })
        res = a.chat("gemini-3.8-flash", [{"role": "user", "content": "Hi Gemini"}])
        self.assertEqual(t.last["url"], f"{BASE}/google/v1beta/models/gemini-3.8-flash:generateContent")
        self.assertEqual(t.last["body"]["contents"][0]["parts"][0]["text"], "Hi Gemini")
        self.assertEqual(res["text"], "Hello from Gemini")
        self.assertEqual(res["usage"], {"input": 15, "output": 7})

    def test_chat_gpt_responses_protocol(self):
        a, t = make({
            "output_text": "Hello from GPT",
            "usage": {"input_tokens": 20, "output_tokens": 10},
        })
        res = a.chat("gpt-5.5", [{"role": "user", "content": "Hi GPT"}])
        self.assertEqual(t.last["url"], f"{BASE}/openai/v1/responses")
        self.assertEqual(t.last["body"]["model"], "gpt-5.5")
        self.assertEqual(res["text"], "Hello from GPT")
        self.assertEqual(res["usage"], {"input": 20, "output": 10})

    def test_empty_answer_raises_retryable(self):
        a, _ = make({"choices": [{"message": {"content": "   "}}]})
        with self.assertRaises(Retryable):
            a.chat("kimi-k2.6", [{"role": "user", "content": "test"}])

    def test_vision(self):
        a, t = make({"choices": [{"message": {"content": "I see an image"}}]})
        res = a.vision("kimi-k2.6", "Describe this", [png()])
        self.assertEqual(t.last["url"], f"{BASE}/openai/v1/chat/completions")
        msgs = t.last["body"]["messages"]
        self.assertEqual(msgs[0]["content"][0]["text"], "Describe this")
        self.assertTrue(msgs[0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(res["text"], "I see an image")

    def test_image_unsupported(self):
        a, _ = make()
        with self.assertRaises(Unsupported):
            a.image("any-model", "a prompt")


if __name__ == "__main__":
    unittest.main()
