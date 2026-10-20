import unittest
from aistudio.character_check import build_character_check_prompt, parse_character_analysis, _FALLBACK_ANALYSIS


class TestCharacterCheck(unittest.TestCase):
    def test_build_prompt(self):
        p = build_character_check_prompt()
        self.assertIn("CHARACTER MASTER SHEET", p)
        self.assertIn("Multiple body angles", p)
        self.assertIn("Multiple facial expressions", p)
        self.assertIn("character_ref_only", p)

    def test_parse_valid_full_sheet(self):
        json_text = '''{
            "is_character_sheet": true,
            "kind": "full_character_sheet",
            "has_multiple_angles": true,
            "has_facial_expressions": true,
            "angles_detected": ["front", "side", "back"],
            "expressions_detected": ["neutral", "happy", "angry"],
            "character_description": "Man in white shirt",
            "summary": "Full turnaround model sheet with expression grid",
            "suggested_prompt": "Character sheet..."
        }'''
        res = parse_character_analysis(json_text)
        self.assertTrue(res["is_character_sheet"])
        self.assertEqual(res["kind"], "full_character_sheet")
        self.assertTrue(res["has_multiple_angles"])
        self.assertTrue(res["has_facial_expressions"])

    def test_parse_single_angle_photo(self):
        json_text = '''{
            "is_character_sheet": false,
            "kind": "character_ref_only",
            "has_multiple_angles": false,
            "has_facial_expressions": false,
            "angles_detected": ["front"],
            "expressions_detected": ["neutral"],
            "character_description": "Elderly man in dhoti walking",
            "summary": "Single photo of a person walking, lacking turnaround views and facial reaction grid",
            "suggested_prompt": "Character reference sheet of elderly man..."
        }'''
        res = parse_character_analysis(json_text)
        self.assertFalse(res["is_character_sheet"])
        self.assertEqual(res["kind"], "character_ref_only")
        self.assertFalse(res["has_multiple_angles"])
        self.assertFalse(res["has_facial_expressions"])

    def test_fallback_on_invalid(self):
        res = parse_character_analysis("not json at all")
        self.assertFalse(res["is_character_sheet"])
        self.assertEqual(res["kind"], "character_ref_only")


if __name__ == "__main__":
    unittest.main()
