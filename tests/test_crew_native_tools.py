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


class ScriptNative:
    tools_mode = "native"

    def __init__(self, replies, cost=0.0):
        self.replies, self.cost, self.seen = list(replies), cost, []

    def __call__(self, messages, tools=None):
        self.seen.append([dict(m) for m in messages])
        reply = self.replies.pop(0) if self.replies else {"tool": "done", "args": {"summary": "finished"}}
        if isinstance(reply, dict) and "tool_calls" in reply:
            return {"text": reply.get("text", ""), "tool_calls": reply["tool_calls"], "cost": self.cost, "usage": {"input": 10, "output": 5}, "model": "fake/script"}
        if isinstance(reply, dict) and "tool" in reply:
            if reply["tool"] == "done":
                return {"text": "", "tool_calls": [{"id": "c_done", "name": "done", "args": reply.get("args", {"summary": "done"})}], "cost": self.cost, "usage": {"input": 10, "output": 5}, "model": "fake/script"}
            return {"text": reply.get("why", ""), "tool_calls": [{"id": "c1", "name": reply["tool"], "args": reply.get("args", {})}], "cost": self.cost, "usage": {"input": 10, "output": 5}, "model": "fake/script"}
        return {"text": str(reply), "tool_calls": [], "cost": self.cost, "usage": {"input": 10, "output": 5}, "model": "fake/script"}


class CrewRuntimeNativeToolsTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from aistudio.service import Workspace
        from aistudio.crew import agents
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Workspace(self.tmp.name)
        self.ws.create_project("demo")
        p = self.ws.pdir("demo")
        (p / "Story.md").write_text("# Initial Story\n", encoding="utf-8")
        fix_dir = unittest.TestCase().defaultTestResult()  # dummy
        from pathlib import Path
        self.fix = Path(__file__).parent / "fixtures" / "agents"
        self.agent = agents.load("echo-writer", dirs=(self.fix,))

    def test_native_tool_calling_executes_free_tool_and_finishes(self):
        from aistudio.crew import runtime
        llm = ScriptNative([
            {"tool": "read_doc", "args": {"name": "demo", "doc": "Story.md"}},
            {"tool": "write_doc", "args": {"name": "demo", "doc": "Story.md", "text": "# Native Story\n"}},
            {"tool": "done", "args": {"summary": "finished story"}},
        ])
        rec = runtime.run(self.ws, "demo", self.agent, "write story", "copilot", llm=llm, tools_mode="native")
        self.assertEqual(rec["status"], "done")
        self.assertEqual(len(rec["steps"]), 3)
        self.assertEqual([s["status"] for s in rec["steps"]], ["ok", "ok", "done"])
        self.assertEqual((self.ws.pdir("demo") / "Story.md").read_text(), "# Native Story\n")
        # Observation was wrapped as untrusted
        last_user_msg = llm.seen[-1][-1]["content"]
        self.assertIn('<tool_result tool="write_doc" untrusted="true">', last_user_msg)

    def test_native_tool_calling_refuses_forbidden_tool(self):
        from aistudio.crew import runtime
        llm = ScriptNative([
            {"tool": "approve_budget", "args": {"name": "demo"}},
            {"tool": "done", "args": {"summary": "attempted approval"}},
        ])
        rec = runtime.run(self.ws, "demo", self.agent, "try approve", "copilot", llm=llm, tools_mode="native")
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["steps"][0]["status"], "refused")
        self.assertEqual(rec["steps"][0]["tool"], "approve_budget")
        self.assertIn("not available to you", rec["steps"][0]["result"])
        last_user_msg = llm.seen[1][-1]["content"]
        self.assertIn('<tool_result tool="approve_budget" untrusted="true">', last_user_msg)

    def test_native_tool_calling_handles_invalid_args(self):
        from aistudio.crew import runtime
        llm = ScriptNative([
            {"tool": "read_doc", "args": {"name": "demo", "bad_arg": 123}},
            {"tool": "done", "args": {"summary": "done"}},
        ])
        rec = runtime.run(self.ws, "demo", self.agent, "bad args", "copilot", llm=llm, tools_mode="native")
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["steps"][0]["status"], "invalid_args")
        self.assertIn("unknown argument 'bad_arg'", rec["steps"][0]["result"])


if __name__ == "__main__":
    unittest.main()
