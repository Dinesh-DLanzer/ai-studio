import tests._hermetic as HERM  # noqa: F401
import copy
import tempfile
import unittest
from pathlib import Path

from aistudio import recipes
from aistudio.domain.common import ServiceError

GOOD = {"id": "t-one", "label": "T", "category": "Test", "consent": "none",
        "inputs": [{"key": "product", "type": "image", "required": True}, {"key": "headline", "type": "text", "max": 20},
                   {"key": "setting", "type": "choice", "options": ["studio", "kitchen"]}],
        "steps": [{"id": "hero", "task": "image_edit", "source": "{product}", "prompt": "In a {setting} scene {headline}"},
                  {"id": "orbit", "task": "image_to_video", "source": "{hero}", "seconds": 4, "direction": {"preset": "360-orbit"}, "prompt": "orbit"},
                  {"id": "edit", "task": "assemble", "clips": ["{orbit}"], "text": [{"text": "{headline}", "at": 0.5}]}]}


class LoaderTests(unittest.TestCase):
    def bad(self, mutate, needle):
        d = copy.deepcopy(GOOD)
        mutate(d)
        with self.assertRaises(recipes.RecipeError) as c:
            recipes.validate(d)
        self.assertIn(needle, str(c.exception))

    def test_good_recipe_passes(self):
        self.assertEqual(recipes.validate(copy.deepcopy(GOOD))["id"], "t-one")

    def test_unknown_placeholder_is_an_error(self):
        self.bad(lambda d: d["steps"][0].update(prompt="x {nope}"), "unknown placeholder")
        self.bad(lambda d: d["steps"][0].update(prompt="x {product}"), "unknown placeholder")      # a file never goes into a prompt
        self.bad(lambda d: d["steps"][0].update(prompt="${ setting }"), "stray brace")
        self.bad(lambda d: d["steps"][0].update(prompt="{a b}"), "stray brace")
        self.bad(lambda d: d["steps"][1].update(source="{edit}"), "later placeholder")
        self.bad(lambda d: d["steps"][1].update(source="{headline}"), "placeholder")           # free text can never be a face/source
        self.bad(lambda d: d["steps"][1].update(source="../x/{hero}"), "whole")

    def test_unknown_keys_and_types_are_errors(self):
        self.bad(lambda d: d.update(evil="x"), "unknown key")
        self.bad(lambda d: d["steps"][0].update(code="__import__('os')"), "bad step")
        self.bad(lambda d: d["inputs"][0].update(type="file"), "type")
        self.bad(lambda d: d.update(consent="maybe"), "consent")
        self.bad(lambda d: d.update(format="nope"), "format")
        self.bad(lambda d: d["steps"][1].update(direction={"preset": "x", "extra": 1}), "direction")

    def test_free_text_never_steers_generation_in_person_recipes(self):
        self.bad(lambda d: d.update(consent="required"), "free text may not steer")

    def test_direction_must_be_a_real_preset(self):
        self.bad(lambda d: d["steps"][1].update(direction={"preset": "nope"}), "camera preset")
        self.bad(lambda d: d["steps"][1].update(direction={"preset": "{headline}"}), "camera preset")

    def test_every_shipped_recipe_loads(self):
        self.assertTrue(recipes.load_all())

    def test_bad_file_is_fatal(self):
        d = Path(tempfile.mkdtemp())
        (d / "x.json").write_text("{nope")
        with self.assertRaises(ServiceError):
            recipes.load_all(d)


if __name__ == "__main__":
    unittest.main()


class TestReviewHardening(unittest.TestCase):
    def test_a_face_task_without_consent_required_is_rejected_by_the_loader(self):
        from aistudio import recipes
        base = {"id": "bad-swap", "label": "Bad", "category": "x", "inputs": [{"key": "photo", "type": "image", "required": True}],
                "steps": [{"id": "swap", "task": "face_swap", "source": {"input": "photo"}}], "consent": "none"}
        with self.assertRaises(Exception) as cm:
            recipes.validate(base)
        self.assertIn("consent", str(cm.exception).lower())

    def test_step_output_paths_from_batch_json_must_stay_inside_the_project(self):
        import tempfile
        from pathlib import Path
        from aistudio import recipes
        p = Path(tempfile.mkdtemp())
        (p / "stills").mkdir()
        (p / "stills" / "a.png").write_bytes(b"x")
        self.assertEqual(recipes._contained(p, "stills/a.png"), "stills/a.png")
        for bad in ("../x.png", "/etc/passwd", "stills/a.txt"):
            with self.assertRaises(recipes.RecipeError):
                recipes._contained(p, bad)
