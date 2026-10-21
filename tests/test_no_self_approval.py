import json
import tempfile
import unittest

import tests._hermetic as HERM  # noqa: F401
from aistudio.service import Workspace, ServiceError
from aistudio import costlog, mcp_server as M
from tests.test_story_convert import MD


class ChatTransport:
    def __init__(self):
        self.responses = []

    def __call__(self, method, path, body=None, raw=False):
        return self.responses.pop(0)


def chat_reply(action=None):
    return {"choices": [{"message": {"content": json.dumps({"reply": "I can prepare that for review.", "brief_updates": {}, "todos_add": [], "storyboard_md": None, "action": action})}}], "usage": {"cost": 0}}


class TestProposalOnlyPaidTools(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.ws = Workspace(tempfile.mkdtemp())
        self.ws.create_project("demo")
        self.ws.put_text("demo", "Story.md", MD)
        self.ws.convert_story("demo")
        self.p = self.ws.pdir("demo")
        (self.p / "stills" / "s01.png").write_bytes(b"PNG")
        (self.p / "stills" / "character.png").write_bytes(b"PNG")
        (self.p / "clips").mkdir(exist_ok=True)
        (self.p / "clips" / "s01_final_a1.mp4").write_bytes(b"FAKEMP4")
        HERM.register_test_media(self.p, "stills/s01.png", "stills/character.png", "clips/s01_final_a1.mp4")

    def budget(self):
        self.ws.estimate("demo", 0.2)
        self.ws.approve_budget("demo")

    def test_human_override_is_marked_in_cost_log(self):
        self.budget()
        budget = json.loads((self.p / "budget.json").read_text(encoding="utf-8"))
        budget["stop_loss"] = 0
        (self.p / "budget.json").write_text(json.dumps(budget), encoding="utf-8")
        (self.p / "stills" / "s01.png").unlink()
        proposal = self.ws.propose("demo", "image", "s01", reveal_code=True)
        self.ws.approve("demo", proposal["id"], proposal["code"])
        self.ws.execute("demo", proposal["id"], override=True)
        self.assertEqual(costlog.read_log(self.p)[-1]["override"], "yes")

    def test_edit_still_is_propose_only_then_logs_after_approval(self):
        before = costlog.read_log(self.p)
        prop = self.ws.edit_still("demo", "s01", "replace the sky")
        self.assertEqual(prop["kind"], "image_edit")
        self.assertEqual(costlog.read_log(self.p), before)
        self.budget()
        self.ws.approve_human("demo", prop["id"])
        result = self.ws.execute("demo", prop["id"])
        self.assertEqual(result["kind"], "image_edit")
        self.assertTrue(costlog.read_log(self.p))

    def test_extend_clip_is_propose_only_then_logs_after_approval(self):
        before = costlog.read_log(self.p)
        prop = self.ws.extend_clip("demo", "s01_final_a1", "continue forward", seconds=6)
        self.assertEqual(prop["kind"], "clip_extend")
        self.assertEqual(costlog.read_log(self.p), before)
        self.budget()
        self.ws.approve_human("demo", prop["id"])
        result = self.ws.execute("demo", prop["id"])
        self.assertEqual(result["kind"], "clip_extend")
        self.assertTrue(costlog.read_log(self.p))

    def test_character_analysis_accepts_project_relative_image_path(self):
        prop = self.ws.analyze_character_image("demo", "stills/character.png")
        self.assertEqual(prop["kind"], "review")
        self.assertEqual(prop["options"]["file"], "stills/character.png")
        self.assertEqual(costlog.read_log(self.p), [])

    def test_analyze_character_is_a_review_proposal(self):
        before = costlog.read_log(self.p)
        prop = self.ws.analyze_character_image("demo", "character")
        self.assertEqual(prop["kind"], "review")
        self.assertEqual(prop["options"]["review_type"], "character")
        self.assertEqual(costlog.read_log(self.p), before)
        self.budget()
        self.ws.approve_human("demo", prop["id"])
        result = self.ws.execute("demo", prop["id"])
        self.assertEqual(result["review_type"], "character")
        self.assertEqual(costlog.read_log(self.p)[-1]["stage"], "vision")

    def test_paid_runner_call_without_grant_is_refused(self):
        from aistudio.roles import GrantRequired
        with self.assertRaises(GrantRequired):
            self.ws.runner().image("do not run", project_dir=self.p)

    def test_edit_and_extend_cannot_execute_without_human_approval(self):
        for prop in (
            self.ws.edit_still("demo", "s01", "change the sky"),
            self.ws.extend_clip("demo", "s01_final_a1", "continue", seconds=6),
            self.ws.analyze_character_image("demo", "character"),
        ):
            with self.assertRaises(ServiceError):
                self.ws.execute("demo", prop["id"])


class TestMcpCannotSelfApprove(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.ws = Workspace(tempfile.mkdtemp())
        self.ws.create_project("demo")
        self.ws.put_text("demo", "Story.md", MD)
        self.ws.convert_story("demo")

    @staticmethod
    def call(ws, tool, **args):
        response = M.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}, ws)
        result = response["result"]
        return json.loads(result["content"][0]["text"]), result["isError"]

    def test_mcp_cannot_approve_a_clip(self):
        result, error = self.call(self.ws, "approve_shot", name="demo", shot_id="s01")
        self.assertTrue(error)
        self.assertIn("human-only", result["error"])

    def test_mcp_cannot_override_gates(self):
        proposal, error = self.call(self.ws, "propose", name="demo", kind="image", target="s01")
        self.assertFalse(error)
        result, error = self.call(self.ws, "run_proposal", name="demo", id=proposal["id"], override=True)
        self.assertTrue(error)
        self.assertIn("human-web-only", result["error"])

    def test_confirm_boolean_is_refused_for_budget_and_proposal(self):
        self.call(self.ws, "estimate", name="demo")
        before = self.ws.overview("demo")["budget"]
        budget, error = self.call(self.ws, "approve_budget", name="demo", confirm=True)
        self.assertTrue(error)
        self.assertIn("not human approval", budget["error"])
        self.assertEqual(self.ws.overview("demo")["budget"], before)
        proposal, error = self.call(self.ws, "propose", name="demo", kind="image", target="s01")
        self.assertFalse(error)
        refused, error = self.call(self.ws, "approve_proposal", name="demo", id=proposal["id"], confirm=True)
        self.assertTrue(error)
        self.assertIn("not human approval", refused["error"])
        self.assertEqual(self.ws.proposal_status("demo", proposal["id"])["status"], "pending")


class TestChatCannotApprove(unittest.TestCase):
    def setUp(self):
        HERM.real_projects(self)
        self.transport = ChatTransport()
        self.ws = Workspace(tempfile.mkdtemp(), transport=self.transport)
        self.ws._fake_for = lambda role, project=None: False
        self.ws.create_project("demo")
        self.ws.put_text("demo", "Story.md", MD)
        self.ws.convert_story("demo")
        self.p = self.ws.pdir("demo")
        images = self.ws._read(self.p, "images.json", {"images": []})
        images["images"].append({"id": "character_01", "kind": "character", "out": "stills/character_01.png", "prompt": "a character", "refs": []})
        self.ws.put_images("demo", images)
        self.ws.brief_put("demo", {"brand": "Test", "goal": "test", "story": "One scene.", "length_seconds": "12", "language": "English", "characters": "Character", "setting": "Studio", "budget_cap": "1"})
        (self.p / "budget.json").write_text(json.dumps({"estimate": 1.0, "stop_loss": 1.3, "approved": False}), encoding="utf-8")

    def send(self, text, action=None):
        self.transport.responses.append(chat_reply(action))
        before_budget = json.loads((self.p / "budget.json").read_text(encoding="utf-8"))
        before_log = costlog.read_log(self.p)
        result = self.ws.chat_send("demo", text)
        after_budget = json.loads((self.p / "budget.json").read_text(encoding="utf-8"))
        self.assertEqual(after_budget, before_budget)
        self.assertEqual(costlog.read_log(self.p), before_log)
        self.assertFalse(any(p.get("status") == "approved" for p in self.ws._read(self.p, "proposals.json", [])))
        return result

    def test_regex_shortcuts_only_return_suggestions(self):
        expected = {
            "create character_01": "generate",
            "approve budget": "approve_budget",
            "generate all": "generate_all",
        }
        for text in ("start", "make it", "create character_01", "approve budget", "generate all"):
            result = self.send(text)
            if text in expected:
                self.assertEqual(result["action"]["type"], expected[text], text)
            self.assertIsNone(result["executed"], text)

    def test_llm_action_only_returns_suggestion(self):
        from unittest.mock import patch
        for action in ({"type": "approve_budget"}, {"type": "generate_all"},
                       {"type": "generate", "kind": "image", "target": "character_01"},
                       {"type": "generate", "kind": "clip", "target": "s01"}):
            with self.subTest(action=action), \
                 patch.object(self.ws, "approve_budget", side_effect=AssertionError("chat approved budget")), \
                 patch.object(self.ws, "approve", side_effect=AssertionError("chat approved proposal")), \
                 patch.object(self.ws, "approve_human", side_effect=AssertionError("chat impersonated human")), \
                 patch.object(self.ws, "execute", side_effect=AssertionError("chat executed")), \
                 patch.object(self.ws, "propose", side_effect=AssertionError("chat accessed approval code")):
                result = self.send("please proceed", action)
                self.assertEqual(result["action"]["type"], action["type"])
                self.assertIsNone(result["executed"])

    def test_start_and_make_only_suggest_when_budget_already_approved(self):
        b = json.loads((self.p / "budget.json").read_text())
        b["approved"] = True
        (self.p / "budget.json").write_text(json.dumps(b))
        for text in ("start", "make it", "create character_01", "generate all"):
            result = self.send(text)
            self.assertIn(result["action"]["type"], ("generate", "generate_all"))
            self.assertIsNone(result["executed"])

    def test_chat_has_no_budget_approval_call(self):
        from inspect import getsource
        from aistudio.domain.chat import ChatDomain
        self.assertNotIn("self.ws.approve_budget", getsource(ChatDomain))


if __name__ == "__main__":
    unittest.main()
