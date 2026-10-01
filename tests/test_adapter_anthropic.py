import unittest
from aistudio.providers.adapters.anthropic import AnthropicAdapter
from aistudio.providers.base import Retryable, Unsupported
from tests._adapter_helpers import FakeTransport, png

CONN = {"id": "a", "type": "anthropic", "secret": {"api_key": "sk-ant-abcdef123456"}}


def make(*answers):
    t = FakeTransport(*answers)
    return AnthropicAdapter(CONN, transport=t), t


class TestAnthropic(unittest.TestCase):
    def test_list_models_and_headers(self):
        a, t = make({"data": [{"id": "claude-x", "display_name": "Claude X"}, {"id": "claude-y"}]})
        got = a.list_models()
        self.assertEqual(t.last["url"], "https://api.anthropic.com/v1/models")
        self.assertEqual(t.last["headers"]["x-api-key"], "sk-ant-abcdef123456")
        self.assertEqual(t.last["headers"]["anthropic-version"], "2023-06-01")
        self.assertEqual(got, [{"id": "claude-x", "name": "Claude X", "capability": "chat"}, {"id": "claude-y", "name": "claude-y", "capability": "chat"}])

    def test_chat_moves_system(self):
        a, t = make({"content": [{"type": "text", "text": "hel"}, {"type": "text", "text": "lo"}], "usage": {"input_tokens": 7, "output_tokens": 3}})
        r = a.chat("claude-x", [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}, {"role": "system", "content": "no emoji"}])
        self.assertEqual(t.last["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(t.last["body"], {"model": "claude-x", "max_tokens": 3500, "system": "be brief\n\nno emoji", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(r, {"text": "hello", "usage": {"input": 7, "output": 3}, "cost": None, "model": "claude-x"})

    def test_chat_options_and_no_system(self):
        a, t = make({"content": [{"type": "text", "text": "x"}]})
        a.chat("m", [{"role": "user", "content": "q"}], {"max_tokens": 10, "temperature": 0.2})
        self.assertNotIn("system", t.last["body"])
        self.assertEqual((t.last["body"]["max_tokens"], t.last["body"]["temperature"]), (10, 0.2))

    def test_chat_empty(self):
        a, _ = make({"content": [{"type": "tool_use"}]})
        with self.assertRaises(Retryable):
            a.chat("m", [])

    def test_vision(self):
        a, t = make({"content": [{"type": "text", "text": "ok"}]})
        a.vision("claude-x", "describe", [png()])
        c = t.last["body"]["messages"][0]["content"]
        self.assertEqual(c[0]["type"], "image")
        self.assertEqual(c[0]["source"]["media_type"], "image/png")
        self.assertEqual(c[1], {"type": "text", "text": "describe"})

    def test_unsupported(self):
        a, _ = make()
        with self.assertRaises(Unsupported):
            a.image("m", "p")
        with self.assertRaises(Unsupported):
            a.video_submit("m", {})


if __name__ == "__main__":
    unittest.main()
