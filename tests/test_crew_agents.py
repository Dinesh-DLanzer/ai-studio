import tests._hermetic as HERM  # noqa: F401
import json
import tempfile
import unittest
from pathlib import Path

from aistudio import tool_registry
from aistudio.crew import agents

FIX = Path(__file__).parent / "fixtures" / "agents"


def md(**kw):
    meta = {"id": "t-agent", "name": "T", "version": "1", "role": "r", "tools": "[read_doc]", **kw}
    return "---\n" + "\n".join(f"{k}: {v}" for k, v in meta.items()) + "\n---\nDo the task.\n"


class TestCrewAgents(unittest.TestCase):
    def test_echo_writer_loads(self):
        a = agents.load("echo-writer", dirs=(FIX,))
        self.assertEqual((a["id"], a["engine"], a["limits"]["max_steps"], a["limits"]["max_llm_usd"]), ("echo-writer", "builtin", 6, 0.05))
        self.assertIn("propose", a["tools"])
        self.assertEqual(len(agents.list_agents(dirs=(agents.BUILTIN_DIR,))), 8)      # the stage-B crew ships (see test_crew_catalog)

    def test_unknown_and_forbidden_tools_are_errors(self):
        with self.assertRaises(agents.AgentError):
            agents.validate(*agents.parse(md(tools="[read_doc, no_such_tool]")))
        for name, t in tool_registry.TOOLS.items():
            if name in tool_registry.crew_tools():
                continue
            with self.assertRaises(agents.AgentError, msg=name):
                agents.validate(*agents.parse(md(tools=f"[get_project, {name}]")))

    def test_strict_shape(self):
        for bad in (md(extra="1"), md(engine="claude_code"), md(id="Bad Id"), md(tools="[]"), "no frontmatter"):
            with self.assertRaises(agents.AgentError):
                agents.validate(*agents.parse(bad))
        with self.assertRaises(agents.AgentError):
            agents.validate({"id": "ok-id", "name": "n", "version": 1, "role": "r", "tools": ["read_doc"], "limits": {"max_steps": 9999}}, "p")

    def test_overrides_change_prompt_and_limits_but_cannot_add_tools(self):
        base = agents.load("echo-writer", dirs=(FIX,))
        s = tempfile.mkdtemp()
        (Path(s) / "agents.json").write_text(json.dumps({"echo-writer": {"prompt": "New prompt", "limits": {"max_steps": 3}}}))
        a = agents.load("echo-writer", s, dirs=(FIX,))
        self.assertEqual((a["prompt"], a["limits"]["max_steps"], a["tools"]), ("New prompt", 3, base["tools"]))
        for bad in ({"tools": ["approve_budget"]}, {"limits": {"max_steps": 9999}}, {"limits": {"bogus": 1}}):
            (Path(s) / "agents.json").write_text(json.dumps({"echo-writer": bad}))
            with self.assertRaises(agents.AgentError):
                agents.load("echo-writer", s, dirs=(FIX,))


if __name__ == "__main__":
    unittest.main()
