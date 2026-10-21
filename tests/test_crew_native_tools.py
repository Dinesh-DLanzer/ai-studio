import json
import unittest
from aistudio.providers.base import Adapter, Unsupported, Retryable
from aistudio.providers.adapters.fake import FakeAdapter
from aistudio.providers.adapters.anthropic import AnthropicAdapter
from aistudio.providers.adapters.openai import OpenAIAdapter
from aistudio.providers.adapters.google import GoogleAdapter
from aistudio.providers.adapters.openrouter import OpenRouterAdapter


class BaseAdapterChatToolsTests(unittest.TestCase):
    def test_base_chat_tools_unsupported(self):
        ad = Adapter({"id": "dummy", "type": "dummy"})
        with self.assertRaises(Unsupported):
            ad.chat_tools("model-x", [], [])


class FakeAdapterChatToolsTests(unittest.TestCase):
    def test_fake_chat_tools_default(self):
        fa = FakeAdapter()
        tools = [{"name": "read_doc", "description": "Read doc", "input_schema": {"type": "object"}}]
        res = fa.chat_tools("fake/llm", [{"role": "user", "content": "hi"}], tools)
        self.assertEqual(res["model"], "fake/llm")
        self.assertEqual(len(res["tool_calls"]), 1)
        self.assertEqual(res["tool_calls"][0]["name"], "read_doc")

    def test_fake_chat_tools_opts(self):
        fa = FakeAdapter()
        custom_tcs = [{"id": "c1", "name": "custom_tool", "args": {"foo": "bar"}}]
        res = fa.chat_tools("fake/llm", [], [], opts={"tool_calls": custom_tcs})
        self.assertEqual(res["tool_calls"], custom_tcs)


class AnthropicChatToolsTests(unittest.TestCase):
    def test_request_and_response(self):
        calls = []

        def mock_transport(method, url, headers=None, body=None, raw=False):
            calls.append({"method": method, "url": url, "headers": headers, "body": body})
            return {
                "id": "msg_123",
                "content": [
                    {"type": "text", "text": "Thinking about the doc..."},
                    {"type": "tool_use", "id": "tu_1", "name": "read_doc", "input": {"doc": "Story.md"}},
                ],
                "usage": {"input_tokens": 15, "output_tokens": 20},
            }

        ad = AnthropicAdapter({"id": "ant", "type": "anthropic", "secret": {"api_key": "sk-ant"}}, transport=mock_transport)
        tools = [{"name": "read_doc", "description": "Read a file", "input_schema": {"type": "object", "properties": {"doc": {"type": "string"}}}}]
        res = ad.chat_tools("claude-3-5-sonnet", [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}], tools)

        self.assertEqual(len(calls), 1)
        req = calls[0]
        self.assertEqual(req["body"]["model"], "claude-3-5-sonnet")
        self.assertEqual(req["body"]["system"], "sys")
        self.assertEqual(req["body"]["tools"][0]["name"], "read_doc")
        self.assertEqual(res["text"], "Thinking about the doc...")
        self.assertEqual(res["tool_calls"], [{"id": "tu_1", "name": "read_doc", "args": {"doc": "Story.md"}}])
        self.assertEqual(res["usage"], {"input": 15, "output": 20})


class OpenAIChatToolsTests(unittest.TestCase):
    def test_request_and_response(self):
        calls = []

        def mock_transport(method, url, headers=None, body=None, raw=False):
            calls.append({"method": method, "url": url, "headers": headers, "body": body})
            return {
                "id": "chatcmpl_1",
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "I will read Story.md",
                        "tool_calls": [{
                            "id": "call_99",
                            "type": "function",
                            "function": {
                                "name": "read_doc",
                                "arguments": json.dumps({"doc": "Story.md"}),
                            },
                        }],
                    },
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 12, "cost": 0.0005},
            }

        ad = OpenAIAdapter({"id": "oa", "type": "openai", "secret": {"api_key": "sk-oa"}}, transport=mock_transport)
        tools = [{"name": "read_doc", "description": "Read doc", "parameters": {"type": "object"}}]
        res = ad.chat_tools("gpt-4o", [{"role": "user", "content": "hi"}], tools)

        self.assertEqual(len(calls), 1)
        req = calls[0]
        self.assertEqual(req["body"]["tools"][0]["function"]["name"], "read_doc")
        self.assertEqual(res["text"], "I will read Story.md")
        self.assertEqual(res["tool_calls"], [{"id": "call_99", "name": "read_doc", "args": {"doc": "Story.md"}}])
        self.assertEqual(res["cost"], 0.0005)


class GoogleChatToolsTests(unittest.TestCase):
    def test_request_and_response(self):
        calls = []

        def mock_transport(method, url, headers=None, body=None, raw=False):
            calls.append({"method": method, "url": url, "headers": headers, "body": body})
            return {
                "candidates": [{
                    "content": {
                        "role": "model",
                        "parts": [
                            {"text": "Calling tool now."},
                            {"functionCall": {"name": "read_doc", "args": {"doc": "Story.md"}}},
                        ],
                    },
                }],
                "usageMetadata": {"promptTokenCount": 25, "candidatesTokenCount": 30},
            }

        ad = GoogleAdapter({"id": "g", "type": "google", "secret": {"api_key": "ai-key"}}, transport=mock_transport)
        tools = [{"name": "read_doc", "description": "Read doc", "parameters": {"type": "object"}}]
        res = ad.chat_tools("gemini-2.5-flash", [{"role": "user", "content": "hi"}], tools)

        self.assertEqual(len(calls), 1)
        req = calls[0]
        self.assertEqual(req["body"]["tools"][0]["functionDeclarations"][0]["name"], "read_doc")
        self.assertEqual(res["text"], "Calling tool now.")
        self.assertEqual(res["tool_calls"], [{"id": "call_1", "name": "read_doc", "args": {"doc": "Story.md"}}])
        self.assertEqual(res["usage"], {"input": 25, "output": 30})


class OpenRouterChatToolsTests(unittest.TestCase):
    def test_request_and_cost(self):
        calls = []

        def mock_transport(method, url, headers=None, body=None, raw=False):
            calls.append({"method": method, "url": url, "headers": headers, "body": body})
            return {
                "choices": [{
                    "message": {
                        "content": None,
                        "tool_calls": [{
                            "id": "tc_or_1",
                            "type": "function",
                            "function": {"name": "done", "arguments": "{\"summary\": \"all done\"}"},
                        }],
                    },
                }],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8, "cost": 0.0012},
            }

        ad = OpenRouterAdapter({"id": "or", "type": "openrouter", "secret": {"api_key": "sk-or"}}, transport=mock_transport)
        tools = [{"name": "done", "description": "done tool"}]
        res = ad.chat_tools("anthropic/claude-3.5-sonnet", [{"role": "user", "content": "finish"}], tools)

        self.assertEqual(len(calls), 1)
        self.assertEqual(res["tool_calls"], [{"id": "tc_or_1", "name": "done", "args": {"summary": "all done"}}])
        self.assertEqual(res["cost"], 0.0012)


if __name__ == "__main__":
    unittest.main()
