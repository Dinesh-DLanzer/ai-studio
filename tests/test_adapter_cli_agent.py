import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aistudio.providers import config as pconf
from aistudio.providers.adapters import cli_agent as ca
from aistudio.providers.base import AuthError, Retryable, Unsupported
from tests._adapter_helpers import png


class FakeRun:
    """Records every command and answers from a queue: (rc, stdout, stderr), a callable(cmd, input, cwd) or an exception."""
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, cmd, input_text=None, cwd=None, timeout=None):
        self.calls.append({"cmd": cmd, "input": input_text, "cwd": cwd, "timeout": timeout})
        a = self.answers.pop(0) if self.answers else (0, "", "")
        if callable(a):
            a = a(cmd, input_text, cwd)
        if isinstance(a, Exception):
            raise a
        return a

    @property
    def last(self):
        return self.calls[-1]


def make(cls, *answers):
    run = FakeRun(*answers)
    return cls({"id": "x", "type": cls.type, "runner": run}), run


def installed():
    return mock.patch("shutil.which", lambda b: "/usr/bin/" + b)


class TestCodexCLI(unittest.TestCase):
    def test_chat_reads_output_file_and_is_read_only(self):
        def write_answer(cmd, inp, cwd):
            Path(cmd[cmd.index("-o") + 1]).write_text("Hello\n")
            return (0, "noise", "")
        a, run = make(ca.CodexCLIAdapter, write_answer)
        with installed():
            r = a.chat("gpt-6-luna", [{"role": "system", "content": "Be brief"}, {"role": "user", "content": "Hi"}])
        c = run.last["cmd"]
        self.assertEqual((r["text"], r["cost"], r["model"]), ("Hello", 0.0, "gpt-6-luna"))
        self.assertEqual(c[1:3], ["exec", "--skip-git-repo-check"])
        self.assertEqual(c[c.index("-s") + 1], "read-only")
        self.assertEqual(c[c.index("-m") + 1], "gpt-6-luna")
        self.assertIn("System: Be brief", run.last["input"])          # prompt goes over stdin
        self.assertNotIn("Hi", c)

    def test_vision_attaches_images(self):
        a, run = make(ca.CodexCLIAdapter, lambda cmd, i, cwd: (Path(cmd[cmd.index("-o") + 1]).write_text("two cats"), (0, "", ""))[1])
        p1, p2 = png("a.png"), png("b.png")
        with installed():
            self.assertEqual(a.vision("m", "what?", [p1, p2])["text"], "two cats")
        c = run.last["cmd"]
        self.assertEqual([c[i + 1] for i, x in enumerate(c) if x == "-i"], [str(Path(p1).resolve()), str(Path(p2).resolve())])


class TestOpenCodeCLI(unittest.TestCase):
    OUT = "\n".join(json.dumps(e) for e in [
        {"type": "step_start", "part": {}}, {"type": "text", "part": {"text": "Hel"}}, {"type": "text", "part": {"text": "lo"}},
        {"type": "step_finish", "part": {"tokens": {"input": 11, "output": 4}}}])

    def test_chat_parses_json_events(self):
        a, run = make(ca.OpenCodeCLIAdapter, (0, self.OUT, ""))
        with installed():
            r = a.chat("anthropic/claude-x", [{"role": "user", "content": "Hi"}])
        self.assertEqual((r["text"], r["usage"]), ("Hello", {"input": 11, "output": 4}))
        c = run.last["cmd"]
        self.assertEqual((c[1], c[c.index("-m") + 1], c[-1]), ("run", "anthropic/claude-x", "Hi"))

    def test_models_listing_and_vision_flag(self):
        a, run = make(ca.OpenCodeCLIAdapter, (0, "anthropic/claude-x\nopencode/kimi-k2.6\nnot a model line\n", ""), (0, self.OUT, ""))
        with installed():
            self.assertEqual([m["id"] for m in a.list_models()], ["opencode/kimi-k2.6", "anthropic/claude-x"])      # opencode/ first
            a.vision("m/x", "see", [png()])
        self.assertIn("-f", run.last["cmd"])


class TestClaudeCLI(unittest.TestCase):
    DOC = json.dumps({"result": "Hi there", "is_error": False, "usage": {"input_tokens": 9, "output_tokens": 40}})

    def test_chat_has_no_tools(self):
        a, run = make(ca.ClaudeCLIAdapter, (0, self.DOC, ""))
        with installed():
            r = a.chat("haiku", [{"role": "user", "content": "Hi"}])
        c = run.last["cmd"]
        self.assertEqual((r["text"], r["usage"]), ("Hi there", {"input": 9, "output": 40}))
        self.assertEqual(c[c.index("--tools") + 1], "")
        self.assertEqual(run.last["input"], "Hi")

    def test_vision_allows_only_read_on_the_image_folder(self):
        a, run = make(ca.ClaudeCLIAdapter, (0, self.DOC, ""))
        p = png("pic.png")
        with installed():
            a.vision("sonnet", "describe", [p])
        c = run.last["cmd"]
        self.assertEqual(c[c.index("--tools") + 1], "Read")
        self.assertEqual(c[c.index("--add-dir") + 1], str(Path(p).resolve().parent))
        self.assertIn(str(Path(p).resolve()), run.last["input"])

    def test_error_result(self):
        a, _ = make(ca.ClaudeCLIAdapter, (0, json.dumps({"is_error": True, "result": "Not logged in"}), ""))
        with installed(), self.assertRaises(AuthError):
            a.chat("haiku", [{"role": "user", "content": "x"}])


class TestAntigravityCLI(unittest.TestCase):
    def test_chat_and_models(self):
        a, run = make(ca.AntigravityCLIAdapter, (0, "Fetching...\ngemini-3.8-flash-low\tGemini 3.8 Flash (Low)\nclaude-sonnet-4-6\tSonnet\n", ""), (0, "OK\n", ""))
        with installed():
            self.assertEqual([m["id"] for m in a.list_models()], ["gemini-3.8-flash-low", "claude-sonnet-4-6"])
            r = a.chat("gemini-3.8-flash-low", [{"role": "user", "content": "Hi"}])
        c = run.last["cmd"]
        self.assertEqual((r["text"], c[1:4], c[-2:]), ("OK", ["--sandbox", "-p", "Hi"], ["--model", "gemini-3.8-flash-low"]))

    def test_no_vision(self):
        a, _ = make(ca.AntigravityCLIAdapter)
        with installed(), self.assertRaises(Unsupported):
            a.vision("m", "x", [png()])


class TestDefaultRun(unittest.TestCase):
    def test_stdin_is_closed_not_inherited(self):
        import sys
        probe = [sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"]
        self.assertEqual(ca.default_run(probe)[1].strip(), "''")
        self.assertEqual(ca.default_run(probe, "hello")[1].strip(), "'hello'")


class TestCommonBehaviour(unittest.TestCase):
    def test_missing_binary(self):
        a, _ = make(ca.CodexCLIAdapter)
        with mock.patch("shutil.which", lambda b: None):
            with self.assertRaises(AuthError):
                a.chat("m", [{"role": "user", "content": "x"}])
            self.assertFalse(a.test()["ok"])

    def test_failures_are_classified(self):
        a, _ = make(ca.CodexCLIAdapter, (1, "", "Error: please log in first"), (1, "", "segfault"), (0, "", ""))
        with installed():
            with self.assertRaises(AuthError):
                a.chat("m", [{"role": "user", "content": "x"}])
            with self.assertRaises(Retryable):
                a.chat("m", [{"role": "user", "content": "x"}])
            with self.assertRaises(Retryable):          # empty answer
                a.chat("m", [{"role": "user", "content": "x"}])

    def test_registered_as_local_providers_without_secrets(self):
        for t, binary in (("codex_cli", "codex"), ("opencode_cli", "opencode"), ("claude_cli", "claude"), ("agy_cli", "agy")):
            self.assertEqual(pconf.needs_binary(t), binary)
            self.assertEqual(pconf.PROVIDER_TYPES[t]["fields"], [])
            self.assertIn("chat", pconf.capabilities_of(t))
        self.assertIn("vision", pconf.capabilities_of("claude_cli"))
        self.assertNotIn("vision", pconf.capabilities_of("agy_cli"))

    def test_models_are_free_by_default(self):
        from aistudio.pricing import Pricing
        self.assertTrue(Pricing().is_free(Pricing().card("claude_cli", "claude_cli", "sonnet")))
        pr = Pricing()
        self.assertTrue(pr.is_free(pr.card("opencode_cli", "opencode_cli", "opencode/kimi-free")))
        self.assertIsNone(pr.card("opencode_cli", "opencode_cli", "anthropic/claude-x"))      # per-token elsewhere: user decides


if __name__ == "__main__":
    unittest.main()
