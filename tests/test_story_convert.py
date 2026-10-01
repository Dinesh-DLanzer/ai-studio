import unittest
from aistudio.storyboard import convert as S

MD = """# DEMO: AI VIDEO AD STORYBOARD

## Concept
**Title:** x

# SHOT-BY-SHOT STORYBOARD

## Shot 01 — 0:00–0:04
### Purpose: HOOK

**Visual**
Ramesh stands outside
his quiet shop.

**Camera**
Slow push-in.

**Action**
He checks his phone.

**Voice** (ON-CAMERA)
> கடை இருக்கு...

**English**
> I have a shop...

**On-screen text**
> SHOP ✓
> INSTAGRAM ✓

**Image**: s01 (Ramesh + shop)

**AI Video Prompt**
> SUBJECT: Ramesh. ACTION: checks phone.

---

## Shot 02 — 0:04–0:08
### Purpose: PAIN

**Visual**
Close-up of a phone.

**Voice** (OFF-CAMERA)
> ஆனா சேல்ஸ் வரவே இல்ல!

**English**
> But no sales!

**Image**: s01

**AI Video Prompt**
> SUBJECT: phone.

## Shot 03 — 0:08–0:12
### Purpose: MUSIC

**Visual**
Montage.

**AI Video Prompt**
> SUBJECT: montage.
"""


class TestStory(unittest.TestCase):
    def setUp(self):
        self.st = S.parse_story(MD)

    def test_parse(self):
        self.assertEqual(self.st["title"], "DEMO")
        self.assertEqual([s["id"] for s in self.st["shots"]], ["s01", "s02", "s03"])
        a = self.st["shots"][0]
        self.assertEqual((a["number"], a["time"], a["purpose"]), (1, "0:00–0:04", "HOOK"))
        self.assertEqual(a["visual"], "Ramesh stands outside his quiet shop.")
        self.assertEqual((a["camera"], a["action"]), ("Slow push-in.", "He checks his phone."))
        self.assertEqual((a["voice_mode"], a["voice_line"], a["english"]), ("on-camera", "கடை இருக்கு...", "I have a shop..."))
        self.assertEqual(a["on_screen_text"], ["SHOP ✓", "INSTAGRAM ✓"])
        self.assertEqual((a["image"], a["prompt"]), ("s01", "SUBJECT: Ramesh. ACTION: checks phone."))
        b, c = self.st["shots"][1], self.st["shots"][2]
        self.assertEqual(b["voice_mode"], "off-camera")
        self.assertEqual((c["voice_mode"], c["voice_line"], c["image"], c["on_screen_text"]), ("silent", "", "", []))

    def test_no_shots(self):
        with self.assertRaises(ValueError):
            S.parse_story("# nothing here")

    def test_shots_doc(self):
        d = S.to_shots_doc(self.st)
        self.assertEqual((d["aspect_ratio"], d["audio"]), ("9:16", False))
        a, b, c = d["shots"]
        self.assertEqual((a["id"], a["model"], a["seconds"], a["resolution"], a["audio"], a["first_frame"]),
                         ("s01", "google/veo-3.1-lite", 4, "720p", True, "stills/s01.png"))
        self.assertEqual(a["prompt"], 'SUBJECT: Ramesh. ACTION: checks phone. AUDIO: The speaker says this line, clearly, lips synced to the words: "கடை இருக்கு..." (I have a shop...).')
        self.assertEqual(b["prompt"], 'SUBJECT: phone. AUDIO: An off-camera narrator says this line, clearly: "ஆனா சேல்ஸ் வரவே இல்ல!" (But no sales!).')
        self.assertEqual((c["audio"], "first_frame" in c, c["prompt"]), (False, False, "SUBJECT: montage."))
        self.assertEqual(a["note"], "HOOK 0:00–0:04")
        self.assertEqual(S.to_shots_doc(self.st, model="m", seconds=6, resolution="480p")["shots"][0]["seconds"], 6)

    def test_language_is_named_in_the_audio_line(self):
        d = S.to_shots_doc(self.st, language="Tamil")
        self.assertEqual(d["language"], "Tamil")
        self.assertIn('says this line in Tamil, clearly, lips synced', d["shots"][0]["prompt"])
        self.assertIn('narrator says this line in Tamil, clearly:', d["shots"][1]["prompt"])
        self.assertNotIn("language", S.to_shots_doc(self.st))

    def test_images_doc(self):
        d = S.to_images_doc(self.st)
        self.assertEqual(d["style"], "")
        self.assertEqual(len(d["images"]), 1)
        self.assertEqual(d["images"][0], {"id": "s01", "kind": "frame", "out": "stills/s01.png", "aspect_ratio": "9:16",
                                          "refs": [], "prompt": "Ramesh stands outside his quiet shop."})


if __name__ == "__main__":
    unittest.main()
