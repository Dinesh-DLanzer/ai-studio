import json
import tempfile
import unittest
from pathlib import Path

from aistudio import editor, project
from aistudio.schemas import load_doc
from aistudio.schemas.migrations import CURRENT, migrate
from aistudio.service import Workspace, ServiceError


class TestRuntimeSchemas(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.ws = Workspace(self.root)
        self.ws.create_project("demo")

    def test_unknown_fields_survive_shots_and_images(self):
        shots = {
            "shots": [{"id": "s1", "model": "fake/video", "seconds": 4,
                       "prompt": "hello", "note": "old", "future": {"x": [1, "தமிழ்"]}}],
            "future_top": {"keep": True},
        }
        images = {
            "images": [{"id": "a", "kind": "character", "out": "a.png",
                        "prompt": "face", "refs": [], "future_asset": [1, 2]}],
            "future_top": "value",
        }
        self.ws.put_shots("demo", shots)
        self.ws.put_images("demo", images)
        self.assertEqual(project.load_json(self.ws.pdir("demo"), "shots.json"),
                         {**shots, "schema_version": 2})
        self.assertEqual(project.load_json(self.ws.pdir("demo"), "images.json"),
                         {**images, "schema_version": 1})

    def test_unknown_fields_survive_edit_brief_and_todos(self):
        edit = {"aspect": "9:16", "tracks": {}, "future": {"nested": True}}
        brief = {"brand": "tea", "future": ["keep"]}
        todos = {"manual": [{"id": "x", "title": "keep", "done": False, "future_item": 42}],
                 "future": {"keep": True}}
        for kind, value in (("edit", edit), ("brief", brief), ("todos", todos)):
            with self.subTest(kind=kind):
                self.assertEqual(load_doc(kind, value), {**value, "schema_version": 1})
        p = self.ws.pdir("demo")
        (p / "brief.json").write_text(json.dumps(brief), encoding="utf-8")
        (p / "todos.json").write_text(json.dumps(todos), encoding="utf-8")
        self.ws.brief_put("demo", {"brand": "tea"})
        saved_brief = json.loads((p / "brief.json").read_text())
        self.assertEqual(saved_brief["future"], ["keep"])
        self.ws.todo_add("demo", "Another task")
        saved_todos = json.loads((p / "todos.json").read_text())
        self.assertTrue(saved_todos["future"]["keep"])
        self.assertEqual(saved_todos["manual"][0]["future_item"], 42)
        self.assertEqual(saved_todos["schema_version"], 1)
        self.ws._apply_todo_md("demo", "## My tasks\n- [x] keep\n")
        self.assertEqual(json.loads((p / "todos.json").read_text())["manual"][0]["future_item"], 42)

    def test_edit_save_preserves_clean_output_and_versions_unknown_keys(self):
        incoming = {"aspect": "1:1", "tracks": {
            "video": [{"id": "clip", "src": "clips/clip.mp4", "in": 0, "out": 1, "future_clip": "keep"}],
            "text": [], "audio": [], "future_tracks": True}, "future": {"keep": True}}
        clean = self.ws.edit_put("demo", incoming)
        saved = json.loads((self.ws.pdir("demo") / "edit.json").read_text())
        self.assertEqual(clean, editor.clean(incoming))
        self.assertEqual(saved["schema_version"], 1)
        self.assertTrue(saved["future"]["keep"])
        self.assertTrue(saved["tracks"]["future_tracks"])
        self.assertEqual(saved["tracks"]["video"][0]["future_clip"], "keep")

    def test_v0_migration_stamps_and_preserves_content_without_mutation(self):
        original = {"shots": [], "future": {"a": 1}}
        before = json.loads(json.dumps(original))
        migrated = migrate("shots", original)
        self.assertEqual(migrated, {**original, "schema_version": 2})
        self.assertEqual(original, before)
        loaded = load_doc("shots", original)
        self.assertEqual(loaded, {**original, "schema_version": 2})
        project.save_json(self.ws.pdir("demo"), "shots.json", loaded)
        self.assertEqual(project.load_json(self.ws.pdir("demo"), "shots.json"), loaded)
        self.assertEqual(load_doc("shots", project.load_json(self.ws.pdir("demo"), "shots.json")), loaded)

    def test_all_document_kinds_have_current_versions(self):
        self.assertEqual(CURRENT, {"shots": 2, "images": 1, "edit": 1, "brief": 1, "todos": 1})

    def test_put_error_strings_remain_unchanged(self):
        cases = (
            (self.ws.put_shots, {"shots": "no"}, "shots must be a list"),
            (self.ws.put_shots, {"shots": [{"id": "s", "model": 3, "seconds": 4, "prompt": "x"}]},
             "shot 0: model must be a string"),
            (self.ws.put_images, {"images": "no"}, "images must be a list"),
            (self.ws.put_images, {"images": [{"id": "a", "kind": "character", "out": "a.png",
                                               "prompt": "p", "refs": ["missing"]}]},
             "image 0: ref 'missing' does not exist"),
        )
        for method, doc, expected in cases:
            with self.subTest(expected=expected), self.assertRaises(ServiceError) as raised:
                method("demo", doc)
            self.assertEqual(str(raised.exception), expected)

    def test_create_project_outputs_validate_and_include_v1(self):
        path = self.ws.pdir("demo")
        shots = project.load_json(path, "shots.json")
        images = project.load_json(path, "images.json")
        self.assertEqual(shots["schema_version"], 2)
        self.assertEqual(images["schema_version"], 1)
        self.assertEqual(project.validate_shots(shots), [])
        self.assertEqual(project.validate_images(images), [])
        self.assertEqual(load_doc("shots", shots), shots)
        self.assertEqual(load_doc("images", images), images)

    def test_load_doc_does_not_mutate_input(self):
        data = {"images": [], "schema_version": 0, "future": ["unchanged"]}
        before = json.loads(json.dumps(data))
        result = load_doc("images", data)
        self.assertEqual(data, before)
        self.assertEqual(result, {**data, "schema_version": 1})

    def test_validate_images_custom_refs_limit(self):
        images = [{"id": str(i), "kind": "character", "out": f"{i}.png", "prompt": "p", "refs": []}
                  for i in range(5)]
        images.append({"id": "target", "kind": "frame", "out": "target.png", "prompt": "p",
                       "refs": [str(i) for i in range(5)]})
        self.assertEqual(project.validate_images({"images": images}),
                         ["image 5: refs must have at most 4 items"])
        self.assertEqual(project.validate_images({"images": images}, max_refs=5), [])


if __name__ == "__main__":
    unittest.main()
