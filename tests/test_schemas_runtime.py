import json
import tempfile
import unittest
from pathlib import Path

from aistudio import project
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
                         {**shots, "schema_version": 1})
        self.assertEqual(project.load_json(self.ws.pdir("demo"), "images.json"),
                         {**images, "schema_version": 1})

    def test_v0_migration_stamps_and_preserves_content_without_mutation(self):
        original = {"shots": [], "future": {"a": 1}}
        before = json.loads(json.dumps(original))
        migrated = migrate("shots", original)
        self.assertEqual(migrated, {**original, "schema_version": 1})
        self.assertEqual(original, before)
        loaded = load_doc("shots", original)
        self.assertEqual(loaded, {**original, "schema_version": 1})
        project.save_json(self.ws.pdir("demo"), "shots.json", loaded)
        self.assertEqual(project.load_json(self.ws.pdir("demo"), "shots.json"), loaded)
        self.assertEqual(load_doc("shots", project.load_json(self.ws.pdir("demo"), "shots.json")), loaded)

    def test_all_document_kinds_have_current_v1(self):
        self.assertEqual(CURRENT, {"shots": 1, "images": 1, "edit": 1, "brief": 1, "todos": 1})

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
        self.assertEqual(shots["schema_version"], 1)
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
