"""Extended MCP tool verification tests."""
import json
import tempfile
import unittest
from aistudio import mcp_server as M
from aistudio.service import Workspace
from tests.test_story_convert import MD
import tests._hermetic as HERM


def call(ws, tool, session=None, **args):
    r = M.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}, ws, session=session)["result"]
    return json.loads(r["content"][0]["text"]), r["isError"]


class TestMcpExtended(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.ws = Workspace(tempfile.mkdtemp())
        self.ws.create_project("demo", test_pipeline=True)
        self.ws.put_text("demo", "Story.md", MD)
        self.ws.convert_story("demo")

    def test_production_progress_and_plan(self):
        b = self.ws.brief_get("demo")
        self.ws.brief_put("demo", {f["key"]: "test" for f in b["fields"] if f["required"]})
        self.ws.estimate("demo")
        self.ws.approve_budget("demo")

        prog, err = call(self.ws, "production_progress", name="demo")
        self.assertFalse(err)
        self.assertIn("groups", prog)
        self.assertTrue(len(prog["queue"]) > 0)

        plan, err = call(self.ws, "generate_all_plan", name="demo")
        self.assertFalse(err)
        self.assertIn("items", plan)
        self.assertIn("total", plan)

    def test_edit_tools(self):
        edit, err = call(self.ws, "get_edit", name="demo")
        self.assertFalse(err)
        self.assertIn("edit", edit)
        self.assertIn("tracks", edit["edit"])

        # Update edit
        doc = edit["edit"]
        doc["aspect"] = "16:9"
        res, err = call(self.ws, "update_edit", name="demo", doc=doc)
        self.assertFalse(err)
        self.assertEqual(res["aspect"], "16:9")

    def test_todo_tools(self):
        todos, err = call(self.ws, "add_todo", name="demo", title="Record voiceover")
        self.assertFalse(err)
        self.assertTrue(any(t["title"] == "Record voiceover" for t in todos["manual"]))
        tid = next(t["id"] for t in todos["manual"] if t["title"] == "Record voiceover")

        toggled, err = call(self.ws, "toggle_todo", name="demo", tid=tid)
        self.assertFalse(err)
        self.assertTrue(next(t["done"] for t in toggled["manual"] if t["id"] == tid))

    def test_trash_tools(self):
        trash, err = call(self.ws, "list_trash")
        self.assertFalse(err)
        self.assertIsInstance(trash, list)

    def test_upload_image_tool(self):
        import base64
        from pathlib import Path
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"0" * 20

        # Upload via local file path
        tmp_file = Path(tempfile.gettempdir()) / "test_actor.png"
        tmp_file.write_bytes(png_bytes)
        try:
            res, err = call(self.ws, "upload_image", name="demo", path=str(tmp_file), id="actor", kind="character")
            self.assertFalse(err)
            self.assertEqual(res["id"], "actor")
            self.assertEqual(res["kind"], "character")
            self.assertTrue(res["registered"])

            # Verify registered in images.json
            imgs = self.ws._read(self.ws.pdir("demo"), "images.json", {"images": []})["images"]
            self.assertTrue(any(i["id"] == "actor" and i["kind"] == "character" for i in imgs))

            # Duplicate upload without replace fails
            dup, err = call(self.ws, "upload_image", name="demo", path=str(tmp_file), id="actor")
            self.assertTrue(err)

            # Upload with replace=True succeeds
            rep, err = call(self.ws, "upload_image", name="demo", path=str(tmp_file), id="actor", replace=True)
            self.assertFalse(err)
            self.assertEqual(rep["id"], "actor")
        finally:
            if tmp_file.exists():
                tmp_file.unlink()

        # Upload via base64 data string
        b64_str = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
        res_b64, err = call(self.ws, "upload_image", name="demo", data=b64_str, id="brand_logo", kind="other")
        self.assertFalse(err)
        self.assertEqual(res_b64["id"], "brand_logo")
        self.assertEqual(res_b64["kind"], "other")

    def test_cli_first_approval_workflow(self):
        b = self.ws.brief_get("demo")
        self.ws.brief_put("demo", {f["key"]: "test" for f in b["fields"] if f["required"]})
        
        # 1. Propose returns CLI approval prompt
        prop, err = call(self.ws, "propose", name="demo", kind="image", target="s01")
        self.assertFalse(err)
        self.assertIn("human_approval", prop)
        self.assertNotIn("code", prop)

        pid = prop["id"]

        # 2. Running without budget approval fails with helpful message
        run_res, err = call(self.ws, "run_proposal", name="demo", id=pid)
        self.assertTrue(err)
        self.assertIn("budget", run_res["error"].lower())

        # 3. Approve budget
        session = M.MCPConnection(lambda method, params: {"action": "accept", "content": {"approve": True}}, {"elicitation": {}})
        bud, err = call(self.ws, "approve_budget", session=session, name="demo")
        self.assertFalse(err)
        self.assertTrue(bud["approved"])

        # 4. Running pending proposal without elicitation returns a fallback challenge.
        run_res, err = call(self.ws, "run_proposal", name="demo", id=pid)
        self.assertFalse(err)
        self.assertTrue(run_res["approval_needed"])
        self.assertNotIn("code", run_res)

        # 5. Elicitation approves and executes in one call.
        run_res, err = call(self.ws, "run_proposal", session=session, name="demo", id=pid)
        self.assertFalse(err)
        self.assertIn("file", run_res)

        # 6. Activity log records the execution for live UI updates
        act = self.ws.activity("demo")
        self.assertTrue(len(act) > 0)
        self.assertEqual(act[0]["id"], pid)
        self.assertEqual(act[0]["status"], "done")
        self.assertIn("file", act[0]["result"])


if __name__ == "__main__":
    unittest.main()
