"""Terminal AI agents (Codex, OpenCode, Claude Code, Antigravity) used as providers.  Standard library only.

Subclasses of aistudio.providers.base.Adapter.  No API key: each CLI uses its own login on this computer.  Every call runs the CLI once,
non-interactively, in an empty temporary folder with the most restrictive mode it offers (no file edits, no shell), sends the prompt, and
returns the printed answer.  capabilities: chat everywhere; vision where the CLI can attach image files (codex -i, opencode -f, claude Read).
Calls ride on the user's own plan, so `cost` is 0.0.  Token counts are filled in when the CLI prints them, else 0.
The process runner is injectable for tests: conn["runner"](cmd, input_text, cwd, timeout) -> (returncode, stdout, stderr).
Errors: CLI missing or not signed in -> AuthError ; timeout / crash / empty answer -> Retryable.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from aistudio.providers import chatgpt_auth
from aistudio.providers.base import Adapter, AuthError, ProviderError, Rejected, Retryable, scrub

LOGIN_HINTS = ("not logged in", "login", "log in", "sign in", "unauthorized", "authentication", "api key", "credentials")
DEFAULT_TIMEOUT = 180


def default_run(cmd, input_text=None, cwd=None, timeout=DEFAULT_TIMEOUT):
    kw = {"input": input_text} if input_text is not None else {"stdin": subprocess.DEVNULL}     # never inherit stdin: some CLIs append it to the prompt
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout, env=dict(os.environ), **kw)
    except FileNotFoundError:
        raise AuthError(f"{Path(cmd[0]).name} is not installed or not in PATH") from None
    except subprocess.TimeoutExpired:
        raise Retryable(f"{Path(cmd[0]).name} timed out after {timeout}s") from None
    except OSError as e:
        raise Retryable(f"could not start {Path(cmd[0]).name}: {e}") from None
    return p.returncode, p.stdout, p.stderr


def flatten(messages):
    """Chat messages -> one prompt string (a lone user message is sent as is)."""
    def text(c):
        return c if isinstance(c, str) else "\n".join(x.get("text", "") for x in c if x.get("type") == "text")
    if len(messages) == 1:
        return text(messages[0].get("content", ""))
    names = {"system": "System", "user": "User", "assistant": "Assistant"}
    return "\n\n".join(f"{names.get(m.get('role'), 'User')}: {text(m.get('content', ''))}" for m in messages)


class CLIAdapter(Adapter):
    binary = ""
    capabilities = frozenset({"chat"})
    fallback_models = []

    def __init__(self, conn, transport=None):
        super().__init__(conn, transport=transport)
        self.run = conn.get("runner") or default_run

    def exe(self):
        path = shutil.which(self.binary)
        if not path:
            raise AuthError(f"{self.binary} is not installed or not in PATH")
        return path

    def _models(self):
        return list(self.fallback_models)

    def list_models(self):
        return [{"id": m, "name": m, "capability": "chat"} for m in self._models()]

    def test(self):
        try:
            self.exe()
            models = self._models()
            if not models:
                return {"ok": False, "message": "no models found for " + self.binary}
            self.chat(models[0], [{"role": "user", "content": "Reply with the single word OK."}])
            return {"ok": True, "message": f"Connected: {self.binary} is signed in"}
        except ProviderError as e:
            return {"ok": False, "message": scrub(e)[:200]}

    # ---- calls
    def _timeout(self, opts):
        t = (opts or {}).get("timeout")
        return t if isinstance(t, (int, float)) and t > 0 else DEFAULT_TIMEOUT

    def _call(self, model, prompt, images, opts):
        with tempfile.TemporaryDirectory(prefix="aistudio-cli-") as d:
            text, usage = self._invoke(self.exe(), model, prompt, list(images), d, self._timeout(opts))
        if not text.strip():
            raise Retryable("empty answer")
        return {"text": text.strip(), "usage": usage, "cost": 0.0, "model": model}

    def chat(self, model, messages, opts=None):
        return self._call(model, flatten(messages), [], opts)

    def vision(self, model, prompt, images, opts=None):
        if "vision" not in self.capabilities:
            self._unsupported("vision")
        return self._call(model, prompt, [str(Path(p).resolve()) for p in images], opts)

    def _check(self, rc, out, err):
        if rc != 0:
            msg = (err or out or "").strip()
            low = msg.lower()
            if any(h in low for h in LOGIN_HINTS):
                raise AuthError(f"{self.binary} is not signed in: {scrub(msg)[:160]}")
            raise Retryable(f"{self.binary} failed: {scrub(msg)[-200:]}")

    def _invoke(self, exe, model, prompt, images, cwd, timeout):
        raise NotImplementedError


class CodexCLIAdapter(CLIAdapter):
    type = "codex_cli"
    binary = "codex"
    capabilities = frozenset({"chat", "vision"})
    fallback_models = ["gpt-5.6-luna", "gpt-5.6-terra"]

    def _models(self):
        from aistudio.providers.adapters.chatgpt import chat_models
        return chat_models(chatgpt_auth.codex_auth_path().parent)

    def _invoke(self, exe, model, prompt, images, cwd, timeout):
        out = Path(cwd) / "answer.txt"
        cmd = [exe, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-m", model, "-o", str(out)]
        for p in images:
            cmd += ["-i", p]
        rc, so, se = self.run(cmd, prompt, cwd, timeout)       # prompt on stdin: no length limit, and `-i` would swallow a positional prompt
        self._check(rc, so, se)
        return (out.read_text(encoding="utf-8") if out.exists() else so), {"input": 0, "output": 0}


class OpenCodeCLIAdapter(CLIAdapter):
    type = "opencode_cli"
    binary = "opencode"
    capabilities = frozenset({"chat", "vision"})

    def _models(self):
        for _ in range(2):              # the first call may only start OpenCode's background service and print nothing
            try:
                rc, so, _err = self.run([self.exe(), "models"], None, None, 60)
            except ProviderError:
                return []
            found = [l.strip() for l in so.splitlines() if re.match(r"^[\w.-]+/\S+$", l.strip())] if rc == 0 else []
            if found:                   # OpenCode's own hosted models first: they work without extra provider keys
                return sorted(found, key=lambda m: (not m.startswith("opencode/"), not m.endswith("-free"), m))
        return []

    def _invoke(self, exe, model, prompt, images, cwd, timeout):
        cmd = [exe, "run", "--format", "json", "-m", model]
        for p in images:
            cmd += ["-f", p]
        rc, so, se = self.run(cmd + [prompt], None, cwd, timeout)
        text, usage = [], {"input": 0, "output": 0}
        for line in so.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            part = ev.get("part") or {}
            if ev.get("type") == "text":
                text.append(part.get("text", ""))
            elif ev.get("type") == "error":
                err = ev.get("error") or {}
                msg = str((err.get("data") or {}).get("message") or err.get("message") or err)[:200]
                raise (AuthError if any(h in msg.lower() for h in LOGIN_HINTS) else Retryable)("opencode: " + scrub(msg))
            tok = part.get("tokens") if isinstance(part.get("tokens"), dict) else None
            if tok:
                usage = {"input": tok.get("input", 0) or 0, "output": tok.get("output", 0) or 0}
        if rc != 0 and not text:
            self._check(rc, "", se)
        return "".join(text), usage


class ClaudeCLIAdapter(CLIAdapter):
    type = "claude_cli"
    binary = "claude"
    capabilities = frozenset({"chat", "vision"})
    fallback_models = ["sonnet", "opus", "haiku"]

    def _invoke(self, exe, model, prompt, images, cwd, timeout):
        cmd = [exe, "-p", "--model", model, "--output-format", "json", "--no-session-persistence", "--permission-prompts", "none"]
        if images:                      # the only tool allowed is Read, so Claude can look at the attached files
            dirs = sorted({str(Path(p).parent) for p in images})
            cmd += ["--tools", "Read"] + [x for d in dirs for x in ("--add-dir", d)]
            prompt += "\n\nImage files to look at (use the Read tool):\n" + "\n".join(images)
        else:
            cmd += ["--tools", ""]
        rc, so, se = self.run(cmd, prompt, cwd, timeout)
        self._check(rc, so, se)
        try:
            doc = json.loads(so)
        except ValueError:
            raise Retryable("claude printed something that is not JSON") from None
        if doc.get("is_error"):
            msg = str(doc.get("result") or "request failed")
            raise (AuthError if any(h in msg.lower() for h in LOGIN_HINTS) else Retryable)("claude: " + scrub(msg)[:200])
        u = doc.get("usage") or {}
        return str(doc.get("result") or ""), {"input": u.get("input_tokens", 0) or 0, "output": u.get("output_tokens", 0) or 0}


class AntigravityCLIAdapter(CLIAdapter):
    type = "agy_cli"
    binary = "agy"
    fallback_models = ["gemini-3.8-flash-low", "gemini-3.1-pro-low"]

    def _models(self):
        try:
            rc, so, _ = self.run([self.exe(), "models"], None, None, 60)
        except ProviderError:
            return list(self.fallback_models)
        ids = [l.split("\t")[0].strip() for l in so.splitlines() if "\t" in l]
        return ids if rc == 0 and ids else list(self.fallback_models)

    def _invoke(self, exe, model, prompt, images, cwd, timeout):
        rc, so, se = self.run([exe, "--sandbox", "-p", prompt, "--model", model], None, cwd, timeout)
        self._check(rc, so, se)
        return so, {"input": 0, "output": 0}
