"""Tests for format loading, validation, and project creation from formats."""
import json
import tempfile
import unittest
from pathlib import Path

from aistudio import formats as F
from aistudio import project as P


class TestFormats(unittest.TestCase):
    """Tests for format loading and validation."""

    def test_load_formats(self):
        """All 11 format files load and validate."""
        fmts = F.load_formats()
        self.assertEqual(len(fmts), 11)
        ids = [f["id"] for f in fmts]
        expected = [
            "cinematic-trailer-16x9",
            "explainer-16x9",
            "festival-greeting",
            "instagram-reel",
            "product-ad",
            "product-showcase-9x16",
            "talking-head-ad",
            "testimonial",
            "tiktok",
            "youtube-16x9",
            "youtube-short",
        ]
        self.assertEqual(sorted(ids), expected)

    def test_get_format(self):
        """get_format returns the correct format by id."""
        fmt = F.get_format("instagram-reel")
        self.assertEqual(fmt["id"], "instagram-reel")
        self.assertEqual(fmt["aspect_ratio"], "9:16")
        self.assertEqual(fmt["shots"], 5)
        self.assertEqual(fmt["audio"], True)

    def test_get_format_not_found(self):
        """get_format raises for unknown id."""
        with self.assertRaises(ValueError) as cm:
            F.get_format("nonexistent")
        self.assertIn("not found", str(cm.exception))

    def test_invalid_aspect_ratio_rejected(self):
        """Validation rejects invalid aspect ratios."""
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.json"
            bad.write_text(json.dumps({
                "id": "bad", "label": "Bad", "aspect_ratio": "21:9",
                "shots": 1, "seconds_per_shot": 1, "resolution": "720p",
                "audio": True, "safe_area": {"top": 0.1, "bottom": 0.1, "left": 0.1, "right": 0.1},
                "caption": {"font": "Poppins", "size": 40, "weight": 700, "y": 0.7, "bg": "#000000AA"},
                "cta": {"text": "CTA", "last_seconds": 2},
                "loudness": -14, "brief": {"length": "10s", "purpose": "test"},
                "suggested_models": {"video": ["m1"]}, "notes": "test"
            }))
            with self.assertRaises(ValueError) as cm:
                F._validate_format(json.loads(bad.read_text()), bad)
            self.assertIn("aspect_ratio", str(cm.exception))

    def test_invalid_safe_area_rejected(self):
        """Validation rejects safe_area values outside 0..1."""
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.json"
            bad.write_text(json.dumps({
                "id": "bad", "label": "Bad", "aspect_ratio": "9:16",
                "shots": 1, "seconds_per_shot": 1, "resolution": "720p",
                "audio": True, "safe_area": {"top": 1.5, "bottom": 0.1, "left": 0.1, "right": 0.1},
                "caption": {"font": "Poppins", "size": 40, "weight": 700, "y": 0.7, "bg": "#000000AA"},
                "cta": {"text": "CTA", "last_seconds": 2},
                "loudness": -14, "brief": {"length": "10s", "purpose": "test"},
                "suggested_models": {"video": ["m1"]}, "notes": "test"
            }))
            with self.assertRaises(ValueError) as cm:
                F._validate_format(json.loads(bad.read_text()), bad)
            self.assertIn("safe_area.top", str(cm.exception))

    def test_shots_less_than_one_rejected(self):
        """Validation rejects shots < 1."""
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.json"
            bad.write_text(json.dumps({
                "id": "bad", "label": "Bad", "aspect_ratio": "9:16",
                "shots": 0, "seconds_per_shot": 1, "resolution": "720p",
                "audio": True, "safe_area": {"top": 0.1, "bottom": 0.1, "left": 0.1, "right": 0.1},
                "caption": {"font": "Poppins", "size": 40, "weight": 700, "y": 0.7, "bg": "#000000AA"},
                "cta": {"text": "CTA", "last_seconds": 2},
                "loudness": -14, "brief": {"length": "10s", "purpose": "test"},
                "suggested_models": {"video": ["m1"]}, "notes": "test"
            }))
            with self.assertRaises(ValueError) as cm:
                F._validate_format(json.loads(bad.read_text()), bad)
            self.assertIn("shots", str(cm.exception))

    def test_missing_notes_rejected(self):
        """Validation requires notes field."""
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.json"
            bad.write_text(json.dumps({
                "id": "bad", "label": "Bad", "aspect_ratio": "9:16",
                "shots": 1, "seconds_per_shot": 1, "resolution": "720p",
                "audio": True, "safe_area": {"top": 0.1, "bottom": 0.1, "left": 0.1, "right": 0.1},
                "caption": {"font": "Poppins", "size": 40, "weight": 700, "y": 0.7, "bg": "#000000AA"},
                "cta": {"text": "CTA", "last_seconds": 2},
                "loudness": -14, "brief": {"length": "10s", "purpose": "test"},
                "suggested_models": {"video": ["m1"]}
            }))
            with self.assertRaises(ValueError) as cm:
                F._validate_format(json.loads(bad.read_text()), bad)
            self.assertIn("notes", str(cm.exception))

    def test_font_from_assets(self):
        """All formats use fonts that exist in assets/fonts/."""
        from aistudio.editor import FONTS
        fmts = F.load_formats()
        for fmt in fmts:
            font = fmt["caption"]["font"]
            self.assertIn(font, FONTS, f"Format {fmt['id']}: font '{font}' not in assets/fonts")


class TestProjectFromFormat(unittest.TestCase):
    """Tests for creating projects from formats."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def _check_project(self, name, format_id, expected_aspect, expected_shots, expected_audio):
        """Helper to create a project and verify key properties."""
        p = P.create_project(self.root, name, format=format_id)
        self.assertTrue(p.exists())

        # shots.json
        shots = json.loads((p / "shots.json").read_text(encoding="utf-8"))
        self.assertEqual(shots["aspect_ratio"], expected_aspect)
        self.assertEqual(shots["audio"], expected_audio)
        self.assertEqual(shots.get("format"), format_id)

        # Story.md has N shot sections
        story = (p / "Story.md").read_text(encoding="utf-8")
        shot_headers = [line for line in story.splitlines() if line.startswith("## Shot ")]
        self.assertEqual(len(shot_headers), expected_shots)

        # brief.md has length/purpose
        brief = (p / "brief.md").read_text(encoding="utf-8")
        self.assertIn("Length:", brief)
        self.assertIn("Purpose:", brief)

        # edit.json exists with aspect + caption defaults
        edit = json.loads((p / "edit.json").read_text(encoding="utf-8"))
        self.assertEqual(edit["aspect"], expected_aspect)
        self.assertIn("subtitles", edit["tracks"])

        return p

    def test_instagram_reel(self):
        self._check_project("reel1", "instagram-reel", "9:16", 5, True)

    def test_youtube_short(self):
        self._check_project("short1", "youtube-short", "9:16", 5, True)

    def test_tiktok(self):
        self._check_project("tiktok1", "tiktok", "9:16", 5, True)

    def test_product_ad(self):
        self._check_project("ad1", "product-ad", "9:16", 6, True)

    def test_product_showcase_9x16(self):
        self._check_project("showcase1", "product-showcase-9x16", "9:16", 7, True)

    def test_talking_head_ad(self):
        self._check_project("talking1", "talking-head-ad", "9:16", 4, True)

    def test_testimonial(self):
        self._check_project("testimony1", "testimonial", "9:16", 5, True)

    def test_festival_greeting(self):
        self._check_project("festival1", "festival-greeting", "9:16", 4, True)

    def test_explainer_16x9(self):
        self._check_project("explainer1", "explainer-16x9", "16:9", 8, True)

    def test_cinematic_trailer_16x9(self):
        self._check_project("trailer1", "cinematic-trailer-16x9", "16:9", 10, True)

    def test_youtube_16x9(self):
        self._check_project("yt1", "youtube-16x9", "16:9", 10, True)

    def test_blank_creation_unchanged(self):
        """format=None behaves exactly as before (9:16, audio=false, no format key)."""
        p = P.create_project(self.root, "blank1")
        shots = json.loads((p / "shots.json").read_text(encoding="utf-8"))
        self.assertEqual(shots["aspect_ratio"], "9:16")
        self.assertEqual(shots["audio"], False)
        self.assertNotIn("format", shots)
        # Story.md should be minimal
        story = (p / "Story.md").read_text(encoding="utf-8")
        self.assertEqual(story.strip(), "# Story for blank1")
        # No edit.json for blank
        self.assertFalse((p / "edit.json").exists())

    def test_invalid_format_id_raises(self):
        """Invalid format id raises ValueError."""
        with self.assertRaises(ValueError) as cm:
            P.create_project(self.root, "badfmt", format="not-a-format")
        self.assertIn("not found", str(cm.exception))

    def test_unknown_ids_leave_no_project_behind(self):
        """A bad format or brand kit is refused before the folder is made (no half-made project)."""
        with self.assertRaises(ValueError):
            P.create_project(self.root, "badfmt", format="not-a-format")
        self.assertFalse((self.root / "badfmt").exists())
        with self.assertRaises(ValueError):
            P.create_project(self.root, "badkit", brand_kit="not-a-kit", kit_root=self.root / "brand_kits")
        self.assertFalse((self.root / "badkit").exists())
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), [])

    def test_unknown_ids_leave_no_project_behind_in_the_service(self):
        """The same through the service: the API answers 400 and the workspace stays clean."""
        from aistudio.service import Workspace
        ws = Workspace(tempfile.mkdtemp())
        with self.assertRaises(Exception):
            ws.create_project("bad", format="not-a-format")
        self.assertFalse((ws.root / "projects" / "bad").exists())
        with self.assertRaises(Exception):
            ws.create_project("bad", brand_kit="not-a-kit")
        self.assertFalse((ws.root / "projects" / "bad").exists())

    def test_no_settings_written(self):
        """No format writes anything under settings/ (no model selection)."""
        p = P.create_project(self.root, "testfmt", format="instagram-reel")
        settings_dir = p / "settings"
        self.assertFalse(settings_dir.exists(), "settings/ directory should not be created")


if __name__ == "__main__":
    unittest.main()