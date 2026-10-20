import unittest

from aistudio.ae_script import build_ae_script


class AfterEffectsScriptTests(unittest.TestCase):
    def test_builds_portrait_comp_with_sequence_and_caption(self):
        script = build_ae_script(
            "Demo", "9:16", 24,
            [
                {"src": "one.mp4", "in": 1, "out": 3, "start": 0},
                {"src": "two.mov", "in": 2, "out": 5, "start": 2},
            ],
            [{"text": "Hello", "start": 0.5, "end": 1.5}],
            "/media",
        )
        self.assertIn("1080, 1920", script)
        self.assertEqual(script.count("ImportOptions(File("), 2)
        self.assertEqual(script.count("addText("), 1)
        self.assertIn("layer1.startTime = -1", script)
        self.assertIn("layer2.startTime = 0", script)
        self.assertIn("layer1.inPoint = 0", script)
        self.assertIn("layer2.outPoint = 5", script)

    def test_escapes_script_strings(self):
        script = build_ae_script(
            'A "project"', "1:1", 30,
            [{"src": 'file\\name "雪".mp4', "in": 0, "out": 1, "start": 0}],
            [{"text": 'quote " slash \\ line\n雪 😀', "start": 0, "end": 1}],
            "/media",
        )
        self.assertIn('file\\\\name \\"\\u96ea\\".mp4', script)
        self.assertIn('quote \\" slash \\\\ line\\n\\u96ea \\ud83d\\ude00', script)
        self.assertNotIn("line\n雪", script)

    def test_empty_clip_and_caption_inputs_raise(self):
        with self.assertRaises(ValueError):
            build_ae_script("Demo", "16:9", 24, [], [], "/media")
        with self.assertRaises(ValueError):
            build_ae_script("Demo", "16:9", 24, [{"src": "a.mp4", "in": 0, "out": 1, "start": 0}], [], "/media")


if __name__ == "__main__":
    unittest.main()
