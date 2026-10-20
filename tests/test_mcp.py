import tests._hermetic as HERM  # noqa: F401  (no real key or network in tests)
import io
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from aistudio import mcp_server as M
from aistudio.service import Workspace
from tests.test_story_convert import MD

FORBIDDEN = {"set_mode", "reveal_code"}


def call(ws, tool, session=None, **args):
    r = M.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}, ws, session=session)["result"]
    return json.loads(r["content"][0]["text"]), r["isError"]


class TestMcp(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.ws = Workspace(tempfile.mkdtemp())

    def test_protocol(self):
        r = M.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, self.ws)["result"]
        self.assertEqual(r["serverInfo"]["name"], "ai-studio")
        self.assertNotIn("elicitation", r["capabilities"])
        self.assertIsNone(M.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, self.ws))
        tools = M.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, self.ws)["result"]["tools"]
        self.assertTrue({"propose", "run_proposal", "convert_story", "get_project", "delete_project", "approve_budget", "approve_proposal"} <= {t["name"] for t in tools})
        self.assertEqual(M.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"}, self.ws)["error"]["code"], -32601)

    def test_approval_tools_require_human_elicitation(self):
        call(self.ws, "create_project", name="demo")
        call(self.ws, "write_doc", name="demo", doc="Story.md", text=MD)
        call(self.ws, "convert_story", name="demo")
        call(self.ws, "estimate", name="demo")
        requests = []
        session = M.MCPConnection(lambda method, params: (requests.append((method, params)) or {"action": "accept", "content": {"approve": True}}), {"elicitation": {}})
        initialize = M.handle({"jsonrpc": "2.0", "id": 10, "method": "initialize", "params": {"capabilities": {"elicitation": {}}}}, self.ws, session=session)
        self.assertIn("elicitation", initialize["result"]["capabilities"])

        out, err = call(self.ws, "approve_budget", session=session, name="demo")
        self.assertFalse(err)
        self.assertTrue(out.get("approved"))
        self.assertEqual(requests[0][0], "elicitation/create")
        self.assertEqual(requests[0][1]["requestedSchema"]["required"], ["approve"])

        prop, err = call(self.ws, "propose", name="demo", kind="image", target="s01")
        self.assertFalse(err)
        out, err = call(self.ws, "approve_proposal", session=session, name="demo", id=prop["id"])
        self.assertFalse(err)
        self.assertTrue(out.get("approved"))

        # An agent-supplied boolean is never approval.
        prop2, _ = call(self.ws, "propose", name="demo", kind="image", target="s01")
        out, err = call(self.ws, "approve_proposal", name="demo", id=prop2["id"], confirm=True)
        self.assertTrue(err)
        self.assertEqual(call(self.ws, "get_proposal", name="demo", id=prop2["id"])[0]["status"], "pending")

        out, err = call(self.ws, "delete_project", name="demo", confirm="wrong")
        self.assertTrue(err)
        out, err = call(self.ws, "delete_project", name="demo", confirm="yes")
        self.assertFalse(err)
        self.assertIn("trash", out)

    def test_decline_and_cancel_leave_budget_unapproved(self):
        call(self.ws, "create_project", name="decline")
        call(self.ws, "write_doc", name="decline", doc="Story.md", text=MD)
        call(self.ws, "convert_story", name="decline")
        call(self.ws, "estimate", name="decline")
        for action in ("decline", "cancel"):
            session = M.MCPConnection(lambda method, params, action=action: {"action": action}, {"elicitation": {}})
            out, err = call(self.ws, "approve_budget", session=session, name="decline")
            self.assertTrue(err)
            self.assertIn(action, out["error"])
            self.assertFalse(self.ws.overview("decline")["budget"]["approved"])

    def test_stdio_nested_elicitation(self):
        home = tempfile.mkdtemp()
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"capabilities": {"elicitation": {}}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "create_project", "arguments": {"name": "demo"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "write_doc", "arguments": {"name": "demo", "doc": "Story.md", "text": MD}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "convert_story", "arguments": {"name": "demo"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "estimate", "arguments": {"name": "demo"}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "approve_budget", "arguments": {"name": "demo"}}},
            {"jsonrpc": "2.0", "id": "server-elicitation-1", "result": {"action": "accept", "content": {"approve": True}}},
        ]
        incoming, outgoing = io.StringIO("\n".join(json.dumps(x) for x in messages) + "\n"), io.StringIO()
        M.serve(incoming, outgoing, self.ws)
        rows = [json.loads(x) for x in outgoing.getvalue().splitlines()]
        self.assertEqual(rows[0]["id"], 1)
        self.assertEqual(rows[-1]["id"], 6)
        self.assertEqual(rows[-1]["result"]["isError"], False)
        self.assertEqual(rows[-2]["method"], "elicitation/create")
        self.assertTrue(self.ws.overview("demo")["budget"]["approved"])

    def test_fallback_code_is_not_returned_to_mcp(self):
        call(self.ws, "create_project", name="demo")
        call(self.ws, "write_doc", name="demo", doc="Story.md", text=MD)
        call(self.ws, "convert_story", name="demo")
        call(self.ws, "estimate", name="demo")
        out, err = call(self.ws, "approve_budget", name="demo")
        self.assertFalse(err)
        self.assertTrue(out["approval_needed"])
        self.assertNotIn("code", out)
        import aistudio.notifications as notice_store
        notice = notice_store.read_approvals(self.ws.root)[0]
        challenge_file = self.ws.pdir("demo") / "approval_challenges.json"
        self.assertTrue(challenge_file.exists())
        self.assertNotIn('"code"', challenge_file.read_text(encoding="utf-8"))
        out, err = call(self.ws, "approve_budget", name="demo", code_id=notice["id"], code=notice["code"])
        self.assertFalse(err)
        self.assertTrue(out["approved"])

    def test_agent_flow_cannot_spend_without_approval(self):
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
        session = M.MCPConnection(lambda method, params: {"action": "accept", "content": {"approve": True}}, {"elicitation": {}})
        call(self.ws, "approve_budget", session=session, name="demo")
        call(self.ws, "approve_proposal", session=session, name="demo", id=prop["id"])
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
