import tests._hermetic  # noqa: F401
import json, tempfile, unittest
from aistudio.service import Workspace, ServiceError

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


class TestImportStills(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(tempfile.mkdtemp())
        self.ws.create_project("old")                      # a project whose images.json is empty (like one made by the old command line tool)
        self.p = self.ws.pdir("old")
        for n in ("Ramesh.png", "Ramesh Shop With Crowed.png", "god-promo-logo.png", "s01.png", "s07-cartoon.png", "photo.jpeg", "notes.txt"):
            (self.p / "stills" / n).write_bytes(PNG if n != "notes.txt" else b"hi")
        (self.p / "stills" / "_discarded").mkdir()
        (self.p / "stills" / "_discarded" / "old.png").write_bytes(PNG)
        self.ws.put_shots("old", {"shots": [{"id": "s01", "model": "m", "seconds": 4, "prompt": "p", "first_frame": "stills/s01.png"},
                                            {"id": "s07", "model": "m", "seconds": 4, "prompt": "p", "first_frame": "stills/s07-cartoon.png"}]})

    def test_detects_only_unregistered_images_and_guesses_kinds(self):
        got = {x["file"]: x for x in self.ws.unregistered_stills("old")}
        self.assertEqual(set(got), {"Ramesh.png", "Ramesh Shop With Crowed.png", "god-promo-logo.png", "s01.png", "s07-cartoon.png", "photo.jpeg"})
        self.assertEqual(got["Ramesh Shop With Crowed.png"]["suggested_id"], "ramesh_shop_with_crowed")
        kinds = {f: x["suggested_kind"] for f, x in got.items()}
        self.assertEqual(kinds, {"Ramesh.png": "character", "Ramesh Shop With Crowed.png": "background", "god-promo-logo.png": "other",
                                 "s01.png": "frame", "s07-cartoon.png": "frame", "photo.jpeg": "character"})
        self.assertTrue(got["s01.png"]["used_by_shots"])
        self.assertFalse(got["Ramesh.png"]["used_by_shots"])

    def test_import_renames_files_registers_assets_and_updates_first_frames(self):
        items = [{"file": "Ramesh.png", "id": "ramesh", "kind": "character"}, {"file": "Ramesh Shop With Crowed.png", "id": "shop_busy", "kind": "background"},
                 {"file": "s01.png", "id": "s01", "kind": "frame"}, {"file": "s07-cartoon.png", "id": "s07_cartoon", "kind": "frame"},
                 {"file": "photo.jpeg", "id": "photo", "kind": "other"}]
        o = self.ws.import_stills("old", items)
        by = {i["id"]: i for i in o["images"]["images"]}
        self.assertEqual({k: v["kind"] for k, v in by.items()}, {"ramesh": "character", "shop_busy": "background", "s01": "frame", "s07_cartoon": "frame", "photo": "other"})
        st = self.p / "stills"
        names = {f.name for f in st.iterdir()}            # real names (exists() ignores case on macOS)
        for f in ("ramesh.png", "shop_busy.png", "s01.png", "s07_cartoon.png", "photo.jpg"):
            self.assertIn(f, names)
        for gone in ("Ramesh.png", "Ramesh Shop With Crowed.png", "s07-cartoon.png", "photo.jpeg"):
            self.assertNotIn(gone, names)
        self.assertEqual((by["photo"]["out"], by["ramesh"]["out"]), ("stills/photo.jpg", "stills/ramesh.png"))
        ff = {s["id"]: s["first_frame"] for s in o["shots"]["shots"]}
        self.assertEqual(ff, {"s01": "stills/s01.png", "s07": "stills/s07_cartoon.png"})        # shots followed the rename
        self.assertEqual([x["file"] for x in self.ws.unregistered_stills("old")], ["god-promo-logo.png"])
        self.assertEqual(json.loads((self.p / "images.json").read_text())["images"][0]["prompt"], "character ramesh")

    def test_import_validates_everything_before_moving_anything(self):
        bad_sets = [[{"file": "Ramesh.png", "id": "x", "kind": "weird"}], [{"file": "nope.png", "id": "x", "kind": "frame"}],
                    [{"file": "notes.txt", "id": "x", "kind": "frame"}], [{"file": "../x.png", "id": "x", "kind": "frame"}],
                    [{"file": "Ramesh.png", "id": "bad id", "kind": "frame"}],
                    [{"file": "Ramesh.png", "id": "dup", "kind": "character"}, {"file": "s01.png", "id": "dup", "kind": "frame"}],
                    [{"file": "Ramesh.png", "id": "s01x", "kind": "character"}, {"file": "s01.png", "id": "ramesh_shop_with_crowed", "kind": "frame"}, {"file": "photo.jpeg", "id": "s01x", "kind": "other"}]]
        for items in bad_sets:
            with self.assertRaises(ServiceError):
                self.ws.import_stills("old", items)
        self.assertIn("Ramesh.png", {f.name for f in (self.p / "stills").iterdir()})               # nothing was moved by the failed attempts
        (self.p / "stills" / "taken.png").write_bytes(PNG)
        with self.assertRaises(ServiceError):
            self.ws.import_stills("old", [{"file": "Ramesh.png", "id": "taken", "kind": "character"}])
        self.assertIn("Ramesh.png", {f.name for f in (self.p / "stills").iterdir()})

    def test_existing_assets_are_not_offered_again(self):
        self.ws.import_stills("old", [{"file": "Ramesh.png", "id": "ramesh", "kind": "character"}])
        self.assertNotIn("ramesh.png", [x["file"] for x in self.ws.unregistered_stills("old")])
        with self.assertRaises(ServiceError):
            self.ws.import_stills("old", [{"file": "s01.png", "id": "ramesh", "kind": "frame"}])   # id already an asset

    def test_the_other_kind_passes_verification_and_lint(self):
        self.ws.import_stills("old", [{"file": "god-promo-logo.png", "id": "logo", "kind": "other"}])
        v = self.ws.verify_status("old")["assets"]
        self.assertNotIn("logo", {f["where"] for f in v["findings"]})


if __name__ == "__main__":
    unittest.main()
