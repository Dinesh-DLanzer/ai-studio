import tests._hermetic as HERM  # noqa: F401  (no real key or network in tests)
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from aistudio import mcp_server as M
from aistudio.service import Workspace
from tests.test_story_convert import MD

FORBIDDEN = {"approve", "approve_budget", "approve_proposal", "approve_shot", "approve_human", "set_mode", "execute", "reveal_code"}


def call(ws, tool, **args):
    r = M.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}, ws)["result"]
    return json.loads(r["content"][0]["text"]), r["isError"]


class TestMcp(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.ws = Workspace(tempfile.mkdtemp())

    def test_protocol(self):
        r = M.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, self.ws)["result"]
        self.assertEqual(r["serverInfo"]["name"], "ai-studio")
        self.assertIsNone(M.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, self.ws))
        tools = M.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, self.ws)["result"]["tools"]
        self.assertTrue({"propose", "run_proposal", "convert_story", "get_project"} <= {t["name"] for t in tools})
        self.assertEqual(M.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"}, self.ws)["error"]["code"], -32601)

    def test_no_approval_tools_exist(self):
        names = {t["name"] for t in M.tool_list()}
        self.assertFalse(names & FORBIDDEN, names & FORBIDDEN)
        for n in names:                       # no tool may even accept an approval code or a mode
            props = M.TOOLS[n][1]["properties"]
            self.assertFalse({"code", "mode"} & set(props), n)

    def test_agent_flow_cannot_spend_without_human(self):
        call(self.ws, "create_project", name="demo")
        call(self.ws, "write_doc", name="demo", doc="Story.md", text=MD)
        self.assertEqual(len(call(self.ws, "convert_story", name="demo")[0]["shots"]["shots"]), 3)
        self.assertFalse(call(self.ws, "estimate", name="demo", failure=0.2)[0]["approved"])
        prop, err = call(self.ws, "propose", name="demo", kind="image", target="s01")
        self.assertFalse(err)
        self.assertNotIn("code", prop)
        self.assertEqual(prop["status"], "pending")
        out, err = call(self.ws, "run_proposal", name="demo", id=prop["id"])
        self.assertTrue(err)                                   # not approved; budget not approved
        self.assertFalse((Path(self.ws.pdir("demo")) / "stills" / "s01.png").exists())
        self.ws.approve_budget("demo")                          # the human, in the UI
        self.ws.approve_human("demo", prop["id"])               # the human, in the UI
        out, err = call(self.ws, "run_proposal", name="demo", id=prop["id"])
        self.assertFalse(err)
        self.assertTrue(out["file"].endswith("s01.png"))
        self.assertEqual(call(self.ws, "get_proposal", name="demo", id=prop["id"])[0]["status"], "used")

    def test_agents_can_read_model_setup_but_not_secrets_or_change_it(self):
        names = {t["name"] for t in M.tool_list()}
        self.assertIn("get_model_setup", names)
        self.assertFalse({n for n in names if any(w in n for w in ("secret", "key", "provider", "roles", "price"))} - {"get_model_setup", "list_providers"})
        self.ws.provider_create({"type": "openai", "secret": {"api_key": "sk-LEAKCANARY-1234567890"}})
        out, err = call(self.ws, "get_model_setup")
        self.assertFalse(err)
        self.assertIn("openai", json.dumps(out))
        self.assertNotIn("LEAKCANARY", json.dumps(out))

    def test_errors(self):
        out, err = call(self.ws, "get_project", name="nope")
        self.assertTrue(err)
        out, err = call(self.ws, "propose", name="nope")
        self.assertTrue(err)
        self.assertIn("missing", out["error"])

    def test_stdio(self):
        home = tempfile.mkdtemp()
        lines = "\n".join(json.dumps(m) for m in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_projects", "arguments": {}}}]) + "\nnot json\n"
        p = subprocess.run([sys.executable, "-m", "aistudio.mcp_server"], input=lines, capture_output=True, text=True,
                           env={**os.environ, "AISTUDIO_HOME": home, "AISTUDIO_NO_KEYRING": "1"}, cwd=str(Path(__file__).resolve().parent.parent))
        out = [json.loads(x) for x in p.stdout.strip().splitlines()]
        self.assertEqual(len(out), 3)
        self.assertEqual(out[1]["result"]["isError"], False)
        self.assertEqual(out[2]["error"]["code"], -32700)


if __name__ == "__main__":
    unittest.main()
