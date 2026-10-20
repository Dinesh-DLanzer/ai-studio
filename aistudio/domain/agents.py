"""Terminal AI agent discovery and subprocess supervision domain."""
import json
import os
import shutil
import subprocess
import threading
from typing import Any, Dict, Iterator, List, Optional
from aistudio.domain.common import ServiceError


class AgentDomain:
    def __init__(self, ws):
        self.ws = ws
        self._active_procs: Dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    def list_agents(self) -> List[Dict[str, Any]]:
        """Detect installed terminal agents on the system."""
        agents = [
            {
                "id": "claude",
                "name": "Claude Code",
                "binary": shutil.which("claude"),
                "detected": shutil.which("claude") is not None,
                "description": "Anthropic's terminal agent with native MCP client support.",
            },
            {
                "id": "agy",
                "name": "Antigravity CLI",
                "binary": shutil.which("agy"),
                "detected": shutil.which("agy") is not None,
                "description": "Google DeepMind's agentic CLI with skills and subagent workflows.",
            },
            {
                "id": "opencode",
                "name": "OpenCode",
                "binary": shutil.which("opencode"),
                "detected": shutil.which("opencode") is not None,
                "description": "Terminal-based coding agent for scriptable bash automation.",
            },
            {
                "id": "codex",
                "name": "Codex CLI",
                "binary": shutil.which("codex"),
                "detected": shutil.which("codex") is not None,
                "description": "OpenAI's terminal coding agent (uses your ChatGPT sign-in).",
            },
        ]
        return agents

    def run_agent_stream(self, agent_id: str, prompt: str, project: Optional[str] = None) -> Iterator[str]:
        """Run an agent subprocess and yield streaming text output chunks."""
        agents = {a["id"]: a for a in self.list_agents()}
        if agent_id not in agents:
            raise ServiceError(f"unknown agent: {agent_id}")
        agent = agents[agent_id]
        if not agent["detected"]:
            raise ServiceError(f"agent binary for '{agent_id}' is not installed or not in PATH")

        cwd = str(self.ws.pdir(project)) if project else str(self.ws.root)
        bin_path = agent["binary"]

        if agent_id == "claude":
            cmd = [bin_path, "-p", prompt, "--permission-prompts", "none"]
        elif agent_id == "agy":
            cmd = [bin_path, "-p", prompt]
        elif agent_id == "codex":
            cmd = [bin_path, "exec", "--skip-git-repo-check", prompt]
        else:
            cmd = [bin_path, "run", prompt]

        env = dict(os.environ)
        env["AISTUDIO_HOME"] = str(self.ws.root)

        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )

        with self._lock:
            self._active_procs[agent_id] = proc

        try:
            if proc.stdout:
                for line in iter(proc.stdout.readline, ""):
                    if line:
                        yield line
            proc.wait()
        finally:
            with self._lock:
                self._active_procs.pop(agent_id, None)

    def abort_agent(self, agent_id: str) -> bool:
        """Terminate an active agent subprocess."""
        with self._lock:
            proc = self._active_procs.get(agent_id)
            if proc:
                proc.terminate()
                return True
        return False
