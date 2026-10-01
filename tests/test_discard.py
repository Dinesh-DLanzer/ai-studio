import json, tempfile, unittest
from pathlib import Path
from aistudio import discard as D


class TestDiscard(unittest.TestCase):
    def setUp(self):
        self.p = Path(tempfile.mkdtemp())
        (self.p / "clips").mkdir()

    def make(self, name="a.mp4", text="x"):
        f = self.p / "clips" / name
        f.write_text(text)
        return f

    def test_discard_moves_and_records(self):
        self.make()
        rec = D.discard_file(self.p, "clips/a.mp4", "bad voice", 0.2)
        self.assertFalse((self.p / "clips/a.mp4").exists())
        self.assertTrue((self.p / "clips/_discarded/a.mp4").exists())
        self.assertEqual((rec["file"], rec["cost"], rec["reason"], rec["original"]),
                         ("clips/_discarded/a.mp4", 0.2, "bad voice", "clips/a.mp4"))
        self.assertIn("when", rec)
        self.assertEqual(json.loads((self.p / "discarded.json").read_text())[0]["file"], "clips/_discarded/a.mp4")
        self.assertEqual(D.list_discarded(self.p), [rec])

    def test_keeps_both_on_name_clash(self):
        self.make(text="one")
        D.discard_file(self.p, "clips/a.mp4")
        self.make(text="two")
        rec = D.discard_file(self.p, "clips/a.mp4")
        self.assertEqual(rec["file"], "clips/_discarded/a__2.mp4")
        self.assertEqual((self.p / "clips/_discarded/a.mp4").read_text(), "one")
        self.assertEqual((self.p / "clips/_discarded/a__2.mp4").read_text(), "two")

    def test_errors(self):
        with self.assertRaises(FileNotFoundError):
            D.discard_file(self.p, "clips/none.mp4")
        for bad in ("/etc/passwd", "../x.mp4", "clips/../../x"):
            with self.assertRaises(ValueError):
                D.discard_file(self.p, bad)
        self.make()
        D.discard_file(self.p, "clips/a.mp4")
        with self.assertRaises(ValueError):
            D.discard_file(self.p, "clips/_discarded/a.mp4")

    def test_restore(self):
        self.make()
        D.discard_file(self.p, "clips/a.mp4", "r", 0.1)
        back = D.restore_file(self.p, "clips/_discarded/a.mp4")
        self.assertEqual(back, self.p / "clips/a.mp4")
        self.assertTrue(back.exists())
        self.assertEqual(D.list_discarded(self.p), [])

    def test_restore_errors(self):
        self.make()
        D.discard_file(self.p, "clips/a.mp4")
        self.make()
        with self.assertRaises(FileExistsError):
            D.restore_file(self.p, "clips/_discarded/a.mp4")
        with self.assertRaises(FileNotFoundError):
            D.restore_file(self.p, "clips/_discarded/zzz.mp4")

    def test_list_empty(self):
        self.assertEqual(D.list_discarded(self.p), [])


if __name__ == "__main__":
    unittest.main()
