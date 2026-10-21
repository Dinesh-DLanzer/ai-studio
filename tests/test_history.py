import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from aistudio import history, project
from aistudio.service import Workspace


class TestDocumentHistory(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.ws = Workspace(self.root)
        self.ws.create_project("demo")
        self.pdir = self.ws.pdir("demo")

    def test_saves_previous_only_when_content_changes(self):
        project.save_json(self.pdir, "brief.json", {"title": "first"})
        self.assertEqual(history.history(self.pdir, "brief.json"), [])
        project.save_json(self.pdir, "brief.json", {"title": "second"})
        rows = history.history(self.pdir, "brief.json")
        self.assertEqual(len(rows), 1)
        self.assertEqual(history.read_version(self.pdir, "brief.json", rows[0]["ts"]),
                         '{\n  "title": "first"\n}')
        project.save_json(self.pdir, "brief.json", {"title": "second"})
        self.assertEqual(len(history.history(self.pdir, "brief.json")), 1)

    def test_failed_save_does_not_write_history(self):
        project.save_json(self.pdir, "brief.json", {"title": "first"})
        with patch.object(Path, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                project.save_json(self.pdir, "brief.json", {"title": "second"})
        self.assertEqual(json.loads((self.pdir / "brief.json").read_text()), {"title": "first"})
        self.assertEqual(history.history(self.pdir, "brief.json"), [])

    def test_story_markdown_writes_are_versioned_as_plain_text(self):
        project.save_text(self.pdir, "Story.md", "first")
        project.save_text(self.pdir, "Story.md", "second")
        row = history.history(self.pdir, "Story.md")[0]
        self.assertEqual(history.read_version(self.pdir, "Story.md", row["ts"]), "first")

    def test_prunes_to_newest_200(self):
        for i in range(202):
            project.save_json(self.pdir, "Story.md", str(i))
        rows = history.history(self.pdir, "Story.md")
        self.assertEqual(len(rows), 200)
        self.assertEqual(history.read_version(self.pdir, "Story.md", rows[0]["ts"]), '"200"')

    def test_restore_is_a_new_save_and_keeps_previous(self):
        project.save_json(self.pdir, "brief.json", {"a": 1})
        project.save_json(self.pdir, "brief.json", {"a": 2})
        old = history.history(self.pdir, "brief.json")[0]
        history.restore(self.pdir, "brief.json", old["ts"])
        self.assertEqual(json.loads((self.pdir / "brief.json").read_text()), {"a": 1})
        rows = history.history(self.pdir, "brief.json")
        self.assertEqual(len(rows), 2)
        self.assertEqual(history.read_version(self.pdir, "brief.json", rows[0]["ts"]), '{\n  "a": 2\n}')

    def test_diff_summary_reports_top_level_keys(self):
        project.save_json(self.pdir, "shots.json", {"shots": [], "old": 1, "same": 1})
        project.save_json(self.pdir, "shots.json", {"shots": [], "new": 2, "same": 2})
        row = history.history(self.pdir, "shots.json")[0]
        self.assertEqual(history.diff_summary(self.pdir, "shots.json", row["ts"]),
                         {"added": ["new"], "removed": ["old"], "changed": ["same"]})

    def test_export_omits_history(self):
        project.save_json(self.pdir, "brief.json", {"a": 1})
        project.save_json(self.pdir, "brief.json", {"a": 2})
        archive = self.ws.export_project("demo")
        with zipfile.ZipFile(archive) as zf:
            self.assertFalse(any(".history/" in name for name in zf.namelist()))


if __name__ == "__main__":
    unittest.main()
