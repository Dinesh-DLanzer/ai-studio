import unittest
from aistudio.vision import image_checklist as I, clip_checklist as C


class TestImageChecklist(unittest.TestCase):
    def test_list(self):
        self.assertEqual(len(I.IMAGE_CHECKLIST), 6)
        self.assertTrue(I.IMAGE_CHECKLIST[0].startswith("The person looks like the same person"))
        self.assertTrue(I.IMAGE_CHECKLIST[5].startswith("The framing is vertical"))

    def test_prompt(self):
        p = I.build_prompt({"id": "s07", "kind": "frame"}, ["ramesh_sheet.png", "shop.png"])
        for needle in ("s07", "frame", "ramesh_sheet.png", "shop.png", "1.", "6.", '"verdict"', "JSON"):
            self.assertIn(needle, p)
        for c in I.IMAGE_CHECKLIST:
            self.assertIn(c, p)
        self.assertIn("none", I.build_prompt({"id": "x", "kind": "character"}, []))

    def test_reexport(self):
        self.assertIs(I.parse_review, C.parse_review)


if __name__ == "__main__":
    unittest.main()
