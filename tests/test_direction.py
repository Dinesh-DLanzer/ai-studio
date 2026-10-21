import json
import unittest
from pathlib import Path

from aistudio.schemas.migrations import migrate
from aistudio.storyboard.direction import ANGLES, FRAMINGS, MOVEMENTS, describe, split, validate_direction
from aistudio.storyboard.convert import parse_story, to_shots_doc
from aistudio.service import ServiceError
from aistudio.domain.spec import resolve
from tests.test_spec import make, shots


class TestDirection(unittest.TestCase):
    def test_all_enum_values_validate_and_describe(self):
        for movement in MOVEMENTS:
            self.assertIn("Camera:", describe({"movement": movement}), movement)
        for framing in FRAMINGS:
            validate_direction({"framing": framing})
        for angle in ANGLES:
            validate_direction({"angle": angle})
        with self.assertRaises(ValueError):
            validate_direction({"movement": "crash-zoom"})

    def test_native_and_prompt_splits_for_two_profiles(self):
        direction = {"movement": "zoom-in", "framing": "close-up", "lens_mm": 50}
        native, prompt = split(direction, {"camera": {"native": ["zoom_in"], "param": "camera_motion"}})
        self.assertEqual(native, {"camera_motion": "zoom_in"})
        self.assertIn("close-up framing", prompt)
        self.assertNotIn("zoom in", prompt)
        native, prompt = split(direction, {"camera": {"native": [], "param": None}})
        self.assertEqual(native, {})
        self.assertIn("zoom in", prompt)
        self.assertIn("50mm lens", prompt)
        native_aliases = {"pan-left": "pan_left", "pan-right": "pan_right", "tilt-up": "tilt_up", "tilt-down": "tilt_down",
                          "dolly-in": "dolly_in", "dolly-out": "dolly_out", "truck-left": "truck_left", "truck-right": "truck_right",
                          "pedestal-up": "pedestal_up", "pedestal-down": "pedestal_down", "orbit-left": "orbit_left", "orbit-right": "orbit_right",
                          "crane-up": "crane_up", "crane-down": "crane_down", "zoom-in": "zoom_in", "zoom-out": "zoom_out", "dolly-zoom": "dolly_zoom"}
        for movement in MOVEMENTS:
            _, prompt = split({"movement": movement}, {"camera": {"native": [], "param": None}})
            self.assertIn("Camera:", prompt)
            token = native_aliases.get(movement)
            native, prompt = split({"movement": movement}, {"camera": {"native": [token] if token else [], "param": "camera_motion"}})
            self.assertEqual(bool(native), token is not None)
            if token:
                self.assertNotIn("Camera: a ", prompt)

    def test_presets_are_valid_and_have_one_line_descriptions(self):
        doc = json.loads(Path("catalog/camera_presets.json").read_text())
        self.assertGreaterEqual(len(doc["presets"]), 25)
        for preset in doc["presets"]:
            validate_direction(preset["direction"])
            self.assertTrue(preset["description"].strip())
            self.assertNotIn("\n", preset["description"])

    def test_shots_v1_to_v2_identity_migration_preserves_extra_keys(self):
        old = {"schema_version": 1, "shots": [{"id": "s1", "unknown": {"keep": True}}], "kept": 42}
        new = migrate("shots", old)
        self.assertEqual(new["schema_version"], 2)
        self.assertEqual(new["shots"], old["shots"])
        self.assertEqual(new["kept"], 42)
        self.assertEqual(migrate("shots", {"shots": []})["schema_version"], 2)

    def test_story_labels_parse_into_direction_and_frames(self):
        story = parse_story("""# Demo
## Shot 01
**Camera move:** dolly-in
**Framing:** medium-close
**Angle:** eye-level
**Lens:** 35mm, f/2.0
**Lighting:** warm side light
**Preset:** slow-push-in
**End frame:** stills/end.png
**Keyframe:** 2, stills/mid.png
""")
        shot = story["shots"][0]
        self.assertEqual(shot["direction"], {"movement": "dolly-in", "framing": "medium-close", "angle": "eye-level", "lighting": "warm side light", "preset": "slow-push-in", "lens_mm": 35, "aperture": "f/2.0"})
        docshot = to_shots_doc(story)["shots"][0]
        self.assertEqual(docshot["end_frame"], "stills/end.png")
        self.assertEqual(docshot["keyframes"], [{"at": 2.0, "image": "stills/mid.png"}])

    def test_shots_without_direction_keep_default_spec_shape(self):
        ws, _ = make(self)
        shots(ws, ("s1", 4, {}))
        result = ws.spec("demo", "clip", "s1")
        self.assertEqual(result["camera"], {"prompt_text": "", "native": {}})
        self.assertNotIn("keyframes", result)

    def test_resolved_direction_and_legacy_camera_precedence(self):
        ws, _ = make(self, {"fk|vid-a": {"camera": {"mode": "native", "param": "camera_motion", "native": ["zoom_in"]}}})
        shots(ws, ("s1", 4, {"direction": {"movement": "zoom-in", "framing": "close-up"}}),
              ("s2", 4, {"camera": "Legacy free-text move", "direction": {"movement": "zoom-in"}}))
        spec = ws.spec("demo", "clip", "s1")
        self.assertEqual(spec["camera"]["native"], {"camera_motion": "zoom_in"})
        self.assertIn("close-up framing", spec["camera"]["prompt_text"])
        legacy = ws.spec("demo", "clip", "s2")["camera"]
        self.assertEqual(legacy, {"prompt_text": "Legacy free-text move", "native": {}})

    def test_missing_end_frame_and_keyframe_are_refused(self):
        ws, _ = make(self)
        shots(ws, ("s1", 4, {"end_frame": "stills/not-yet.png"}))
        with self.assertRaisesRegex(ServiceError, "end frame missing: stills/not-yet.png"):
            resolve(ws, ws.pdir("demo"), "clip", "s1")
        shots(ws, ("s1", 4, {"keyframes": [{"at": 1, "image": "stills/mid.png"}]}))
        with self.assertRaisesRegex(ServiceError, "keyframe missing: stills/mid.png"):
            resolve(ws, ws.pdir("demo"), "clip", "s1")

    def test_reference_priority_roles_and_warning(self):
        ws, _ = make(self, {"fk|vid-a": {"references": {"max": 2}}})
        ws.put_images("demo", {"images": [
            {"id": "product", "kind": "other", "out": "stills/product.png", "prompt": "p", "refs": []},
            {"id": "place", "kind": "background", "out": "stills/place.png", "prompt": "p", "refs": []},
            {"id": "person", "kind": "character", "out": "stills/person.png", "prompt": "p", "refs": []},
        ]})
        shots(ws, ("s1", 4, {"refs": ["product", "place", "person"]}))
        spec = ws.spec("demo", "clip", "s1")
        self.assertEqual([(r["id"], r["role"]) for r in spec["refs"]], [("person", "character"), ("place", "location")])
        self.assertTrue(any("dropped: product" in w for w in spec["warnings"]))


if __name__ == "__main__":
    unittest.main()
