import unittest
from aistudio import languages as L


class TestLanguages(unittest.TestCase):
    def test_canonical_and_info(self):
        self.assertEqual(L.canonical(" tamil "), "Tamil")
        self.assertEqual(L.canonical("Klingon"), "Klingon")
        self.assertEqual((L.info("Tamil")["tested"], L.info("english")["tested"], L.info("Hindi")["tested"]), (True, True, False))
        self.assertFalse(L.info("Klingon")["known"])

    def test_script_ratio(self):
        self.assertEqual(L.script_ratio("கடை இருக்கு", "Tamil"), 1.0)
        self.assertEqual(L.script_ratio("kadai irukku", "Tamil"), 0.0)          # Tanglish: wrong script for Tamil
        self.assertAlmostEqual(L.script_ratio("கடை shop", "Tamil"), 1 / 3, places=2)   # vowel signs are marks, not letters
        self.assertIsNone(L.script_ratio("hello", "English"))                    # Latin languages have no script check
        self.assertIsNone(L.script_ratio("123 !!", "Tamil"))                     # no letters
        self.assertEqual(L.script_ratio("नमस्ते", "Hindi"), 1.0)

    def test_latin_and_split(self):
        self.assertEqual(L.latin_ratio("hello"), 1.0)
        self.assertEqual(L.latin_ratio("கடை"), 0.0)
        self.assertEqual(L.split_languages("tamil, English and hindi"), ["Tamil", "English", "Hindi"])


if __name__ == "__main__":
    unittest.main()
