import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from aistudio import brand_kits, project, trash


class TestBrandKits(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.logo = self.root / "source.png"
        Image.new("RGB", (20, 20), (225, 70, 35)).save(self.logo)

    def test_create_kit_derives_palette_and_copies_verified_logo(self):
        kit = brand_kits.create_kit(self.root, "Acme Brand", logo_path=self.logo)
        self.assertEqual(kit["name"], "Acme Brand")
        self.assertEqual(kit["palette"], ["#e14623"])
        kit_dir = self.root / "brand_kits" / "acme-brand"
        self.assertTrue((kit_dir / "logo.png").is_file())
        self.assertEqual(json.loads((kit_dir / "kit.json").read_text()), kit)

    def test_validation_and_safe_ids(self):
        for fields in (
            {"palette": ["red"]},
            {"fonts": {"heading": "NotAFont", "body": "Poppins"}},
            {"watermark": {"pos": "somewhere", "opacity": 0.5}},
            {"watermark": {"pos": "top-right", "opacity": 1.1}},
            {"caption": {"font": "Poppins", "size": -1, "weight": 700, "y": 0.5, "bg": "#000000"}},
        ):
            with self.assertRaises(ValueError):
                brand_kits.create_kit(self.root, "Bad", **fields)
        for kit_id in ("../escape", "a/b", "a\\b", "..", "UpperCase"):
            with self.assertRaises(ValueError):
                brand_kits.get_kit(self.root, kit_id)
        bad_logo = self.root / "not-image.png"
        bad_logo.write_text("not an image")
        with self.assertRaises(ValueError):
            brand_kits.create_kit(self.root, "Bad Logo", logo_path=bad_logo)

    def test_unknown_fields_survive_update_and_delete_moves_to_trash(self):
        kit = brand_kits.create_kit(self.root, "Acme", custom_meta={"x": 1})
        updated = brand_kits.update_kit(self.root, "acme", style_words="bright")
        self.assertEqual(updated["custom_meta"], {"x": 1})
        self.assertEqual(brand_kits.list_kits(self.root), [updated])
        deleted = brand_kits.delete_kit(self.root, "acme")
        self.assertFalse((self.root / "brand_kits" / "acme").exists())
        self.assertTrue(deleted.exists())
        self.assertEqual(json.loads((deleted / "kit.json").read_text())["name"], "Acme")

    def test_attach_is_idempotent_and_export_contains_self_contained_copy(self):
        kit = brand_kits.create_kit(self.root, "Acme", logo_path=self.logo, style_words="clean, bright")
        pdir = project.create_project(self.root / "projects", "demo")
        brand_kits.attach_kit(pdir, self.root / "brand_kits", "acme")
        brand_kits.attach_kit(pdir, self.root / "brand_kits", "acme")
        shots = project.load_json(pdir, "shots.json")
        self.assertEqual(shots["brand_kit"], "acme")
        self.assertEqual(project.load_json(pdir, "images.json")["style"], "clean, bright")
        self.assertEqual(json.loads((pdir / "brand" / "kit.json").read_text()), kit)
        self.assertTrue((pdir / "brand" / "logo.png").is_file())
        self.assertEqual(brand_kits.avoid_terms(pdir), kit["avoid"])
        images = project.load_json(pdir, "images.json")
        images["style"] = "project-specific style"
        project.save_json(pdir, "images.json", images)
        brand_kits.attach_kit(pdir, self.root / "brand_kits", "acme")
        self.assertEqual(project.load_json(pdir, "images.json")["style"], "project-specific style")
        archive = trash.zip_project(pdir)
        try:
            with zipfile.ZipFile(archive) as z:
                names = z.namelist()
                self.assertIn("demo/brand/kit.json", names)
                self.assertIn("demo/brand/logo.png", names)
                self.assertEqual(json.loads(z.read("demo/brand/kit.json")), kit)
        finally:
            archive.unlink(missing_ok=True)

    def test_create_project_can_attach_kit(self):
        brand_kits.create_kit(self.root, "Acme")
        pdir = project.create_project(
            self.root / "projects", "new-project", brand_kit="acme",
            kit_root=self.root / "brand_kits",
        )
        self.assertEqual(project.load_json(pdir, "shots.json")["brand_kit"], "acme")


if __name__ == "__main__":
    unittest.main()
