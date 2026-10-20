import json
import tempfile
import unittest

import tests._hermetic as HERM  # noqa: F401
from aistudio.service import Workspace, ServiceError
from aistudio import costlog
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

    def budget(self):
        self.ws.estimate("demo", 0.2)
        self.ws.approve_budget("demo")

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

    def test_edit_and_extend_cannot_execute_without_human_approval(self):
        for prop in (
            self.ws.edit_still("demo", "s01", "change the sky"),
            self.ws.extend_clip("demo", "s01_final_a1", "continue", seconds=6),
            self.ws.analyze_character_image("demo", "character"),
        ):
            with self.assertRaises(ServiceError):
                self.ws.execute("demo", prop["id"])


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
        result = self.send("please proceed", {"type": "approve_budget"})
        self.assertEqual(result["action"], {"type": "approve_budget", "kind": "image", "target": ""})
        self.assertIsNone(result["executed"])

    def test_chat_has_no_budget_approval_call(self):
        from inspect import getsource
        from aistudio.domain.chat import ChatDomain
        self.assertNotIn("self.ws.approve_budget", getsource(ChatDomain))


if __name__ == "__main__":
    unittest.main()
