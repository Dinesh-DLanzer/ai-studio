import tempfile
import unittest

import tests._hermetic as HERM  # noqa: F401
from aistudio.service import Workspace, ServiceError
from aistudio import costlog
from tests.test_story_convert import MD


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


if __name__ == "__main__":
    unittest.main()
