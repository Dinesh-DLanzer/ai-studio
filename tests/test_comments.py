import json
import tempfile
import unittest
from pathlib import Path

from aistudio import comments, history, project
from aistudio.schemas import load_doc
from aistudio.service import Workspace, ServiceError


class TestComments(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.ws = Workspace(self.root)
        self.pname = "test-proj"
        self.ws.create_project(self.pname)
        self.pdir = self.ws.pdir(self.pname)

    def test_validation_strict(self):
        # Valid targets
        for target in ("edit", "shot:s01", "asset:hero_img", "shot:s-99_b"):
            c = comments.add_comment(self.pdir, target, "Looks good", "Alice", time=12.5)
            self.assertEqual(c["target"], target)
            self.assertEqual(c["author"], "Alice")
            self.assertEqual(c["text"], "Looks good")
            self.assertEqual(c["time"], 12.5)
            self.assertEqual(c["status"], "open")
            self.assertTrue(c["id"].startswith("c_"))

        # Invalid targets
        for bad_target in ("", "shot:", "asset:", "unknown", "shot:../escape", "edit:12"):
            with self.assertRaises((ValueError, ServiceError)):
                comments.add_comment(self.pdir, bad_target, "test", "Alice")

        # Author caps and control char stripping
        c = comments.add_comment(self.pdir, "edit", "Hello", "Bob\x00\x08\x1fDisplay")
        self.assertEqual(c["author"], "BobDisplay")

        with self.assertRaises((ValueError, ServiceError)):
            comments.add_comment(self.pdir, "edit", "Hello", "A" * 65)

        with self.assertRaises((ValueError, ServiceError)):
            comments.add_comment(self.pdir, "edit", "Hello", "   \t\n  ")

        # Text caps and control char stripping
        c = comments.add_comment(self.pdir, "edit", "Line1\x00\x07\nLine2", "Alice")
        self.assertEqual(c["text"], "Line1\nLine2")

        with self.assertRaises((ValueError, ServiceError)):
            comments.add_comment(self.pdir, "edit", "A" * 2001, "Alice")

        with self.assertRaises((ValueError, ServiceError)):
            comments.add_comment(self.pdir, "edit", "   ", "Alice")

        # Time validation
        with self.assertRaises((ValueError, ServiceError)):
            comments.add_comment(self.pdir, "edit", "test", "Alice", time=-1.0)

        c = comments.add_comment(self.pdir, "edit", "No timecode", "Alice", time=None)
        self.assertIsNone(c["time"])

    def test_comment_lifecycle_and_history(self):
        c1 = comments.add_comment(self.pdir, "edit", "First comment", "Alice", time=1.0)
        c2 = comments.add_comment(self.pdir, "shot:s01", "Second comment", "Bob", time=2.0)

        # List all
        all_c = comments.list_comments(self.pdir)
        self.assertEqual(len(all_c), 2)

        # List by target
        shot_c = comments.list_comments(self.pdir, target="shot:s01")
        self.assertEqual(len(shot_c), 1)
        self.assertEqual(shot_c[0]["id"], c2["id"])

        # Resolve
        resolved = comments.resolve_comment(self.pdir, c1["id"])
        self.assertEqual(resolved["status"], "resolved")

        # List by status
        open_c = comments.list_comments(self.pdir, status="open")
        self.assertEqual(len(open_c), 1)
        self.assertEqual(open_c[0]["id"], c2["id"])

        resolved_c = comments.list_comments(self.pdir, status="resolved")
        self.assertEqual(len(resolved_c), 1)
        self.assertEqual(resolved_c[0]["id"], c1["id"])

        # Reopen
        reopened = comments.reopen_comment(self.pdir, c1["id"])
        self.assertEqual(reopened["status"], "open")
        self.assertEqual(len(comments.list_comments(self.pdir, status="open")), 2)

        # Delete
        comments.delete_comment(self.pdir, c2["id"])
        self.assertEqual(len(comments.list_comments(self.pdir)), 1)
        self.assertEqual(comments.list_comments(self.pdir)[0]["id"], c1["id"])

        # Verify history versions exist for comments.json
        hist = history.history(self.pdir, "comments.json")
        self.assertGreater(len(hist), 0)

    def test_feedback_import_dedupe_and_caps(self):
        # Initial comment in project
        c_init = comments.add_comment(self.pdir, "edit", "Existing comment", "Director", cid="c_existing")

        feedback_data = {
            "comments": [
                {
                    "id": "c_existing",
                    "target": "edit",
                    "time": 0.5,
                    "author": "Reviewer 1",
                    "text": "Duplicate should be skipped",
                    "status": "open",
                    "created": "2026-10-21T10:00:00Z"
                },
                {
                    "id": "c_new_1",
                    "target": "shot:s02",
                    "time": 4.2,
                    "author": "Priya",
                    "text": "Pacing is slow here",
                    "status": "open",
                    "created": "2026-10-21T10:05:00Z"
                }
            ]
        }

        res = comments.import_feedback(self.ws, self.pname, json.dumps(feedback_data))
        self.assertEqual(res["imported"], 1)
        self.assertEqual(res["total"], 2)

        all_c = comments.list_comments(self.pdir)
        self.assertEqual(len(all_c), 2)
        new_c = next(c for c in all_c if c["id"] == "c_new_1")
        self.assertEqual(new_c["source"], "reviewer")
        self.assertEqual(new_c["author"], "Priya")

        # Test size cap > 1 MB
        large_json = json.dumps({"comments": [{"id": f"c_{i}", "target": "edit", "author": "A", "text": "X" * 1000} for i in range(1100)]})
        self.assertGreater(len(large_json.encode("utf-8")), 1024 * 1024)
        with self.assertRaises((ValueError, ServiceError)):
            comments.import_feedback(self.ws, self.pname, large_json)

        # Test comment count cap > 500
        too_many = json.dumps({"comments": [{"id": f"c_{i}", "target": "edit", "author": "A", "text": "short"} for i in range(501)]})
        with self.assertRaises((ValueError, ServiceError)):
            comments.import_feedback(self.ws, self.pname, too_many)

    def test_schema_load_doc_and_extras(self):
        raw = {
            "schema_version": 1,
            "comments": [
                {
                    "id": "c_1",
                    "target": "edit",
                    "time": 2.5,
                    "author": "Sam",
                    "text": "Cool",
                    "status": "open",
                    "created": "2026-10-21T12:00:00Z",
                    "future_comment_field": 123
                }
            ],
            "future_top_key": "preserved"
        }
        loaded = comments.load_comments_doc(raw)
        self.assertEqual(loaded["schema_version"], 1)
        self.assertEqual(loaded["future_top_key"], "preserved")
        self.assertEqual(loaded["comments"][0]["future_comment_field"], 123)


if __name__ == "__main__":
    unittest.main()
