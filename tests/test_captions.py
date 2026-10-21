import json
import tempfile
import unicodedata
import unittest
from pathlib import Path

import tests._hermetic  # noqa: F401
from aistudio import captions, editor


TAMIL = "கடையில் தமிழ் பால் விற்கிறார்கள்"
LONG_TAMIL_WORD = "கோயில்கோட்டையில்"


class TestBuildCues(unittest.TestCase):
    def test_even_spread_without_word_timestamps(self):
        cues = captions.build_cues("Hello world, this is a test.", duration=4.0)
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0]["text"], "Hello world, this is a test.")
        self.assertAlmostEqual(cues[0]["start"], 0.0)
        self.assertAlmostEqual(cues[0]["end"], 4.0)

    def test_even_spread_gives_every_word_the_same_time(self):
        cues = captions.build_cues("one two three four", duration=4.0, max_chars=10, max_lines=1)
        self.assertEqual([c["text"] for c in cues], ["one two", "three four"])
        self.assertAlmostEqual(cues[0]["start"], 0.0)
        self.assertAlmostEqual(cues[0]["end"], 2.0)          # two words, two seconds
        self.assertAlmostEqual(cues[1]["start"], 2.0)
        self.assertAlmostEqual(cues[1]["end"], 4.0)

    def test_alignment_uses_the_script_text_and_the_word_times(self):
        script = "The shop opens at seven."
        words = [{"text": "The", "start": 0.0, "end": 0.4},
                 {"text": "shop", "start": 0.4, "end": 0.9},
                 {"text": "opens", "start": 0.9, "end": 1.4},
                 {"text": "at", "start": 1.4, "end": 1.6},
                 {"text": "seven", "start": 1.6, "end": 2.2}]
        cues = captions.build_cues(script, words=words, duration=2.2)
        self.assertEqual(" ".join(c["text"] for c in cues), script)
        self.assertAlmostEqual(cues[0]["start"], 0.0)
        self.assertAlmostEqual(cues[0]["end"], 2.2)

    def test_alignment_drops_words_the_script_does_not_have(self):
        """The transcription heard something extra: the caption keeps the script's words only."""
        words = [{"text": "The", "start": 0.0, "end": 0.4},
                 {"text": "um", "start": 0.4, "end": 0.6},
                 {"text": "shop", "start": 0.6, "end": 1.0},
                 {"text": "opens", "start": 1.0, "end": 1.5}]
        cues = captions.build_cues("The shop opens.", words=words, duration=1.5)
        text = " ".join(c["text"] for c in cues)
        self.assertNotIn("um", text)
        self.assertEqual(text, "The shop opens.")

    def test_alignment_keeps_a_script_word_the_transcriber_missed(self):
        words = [{"text": "The", "start": 0.0, "end": 0.4},
                 {"text": "opens", "start": 0.8, "end": 1.2}]
        cues = captions.build_cues("The shop opens.", words=words, duration=1.2)
        text = " ".join(c["text"] for c in cues)
        self.assertEqual(text, "The shop opens.")           # the missing word is still captioned
        self.assertLessEqual(cues[0]["end"], 1.2)

    def test_alignment_never_invents_a_word(self):
        words = [{"text": "completely", "start": 0.0, "end": 0.5},
                 {"text": "different", "start": 0.5, "end": 1.0}]
        cues = captions.build_cues("The shop opens.", words=words, duration=1.0)
        text = " ".join(c["text"] for c in cues)
        for word in ("completely", "different"):
            self.assertNotIn(word, text)

    def test_cues_break_at_a_sentence_end(self):
        script = "First sentence here. Second sentence here."
        cues = captions.build_cues(script, duration=6.0)
        self.assertEqual(len(cues), 2)
        self.assertTrue(cues[0]["text"].endswith("."))
        self.assertTrue(cues[1]["text"].endswith("."))

    def test_cue_text_stays_inside_the_line_limits(self):
        script = "word " * 40
        cues = captions.build_cues(script, duration=20.0, max_chars=20, max_lines=2)
        self.assertGreater(len(cues), 1)
        for cue in cues:
            for line in cue["text"].split("\n"):
                self.assertLessEqual(len(line), 20)
            self.assertLessEqual(len(cue["text"].split("\n")), 2)

    def test_times_are_monotonic(self):
        words = [{"text": "a", "start": 0.0, "end": 0.1},
                 {"text": "b", "start": 0.05, "end": 0.2},
                 {"text": "c", "start": 0.9, "end": 1.0}]
        cues = captions.build_cues("a b c d e", words=words, duration=1.0)
        starts = [c["start"] for c in cues]
        ends = [c["end"] for c in cues]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(ends, sorted(ends))
        for cue in cues:
            self.assertGreater(cue["end"], cue["start"])
            self.assertGreaterEqual(cue["end"] - cue["start"], captions.MIN_CUE - 1e-6)

    def test_empty_script_gives_no_cues(self):
        self.assertEqual(captions.build_cues("", duration=3.0), [])
        self.assertEqual(captions.build_cues("   ", duration=3.0), [])

    def test_tamil_cue_keeps_its_combining_marks(self):
        cues = captions.build_cues(TAMIL, duration=6.0, max_chars=10, max_lines=2)
        self.assertTrue(cues)
        joined = "".join("".join(c["text"].split()) for c in cues)
        self.assertEqual(joined, TAMIL.replace(" ", ""))
        for cue in cues:
            for line in cue["text"].split("\n"):
                self.assertLessEqual(len(line), 10)
                self.assertEqual(unicodedata.combining(line[0]), 0)   # no mark starts a line

    def test_a_long_tamil_word_is_cut_between_clusters(self):
        pieces = captions.split_word(LONG_TAMIL_WORD, 5)
        self.assertGreater(len(pieces), 1)
        self.assertEqual("".join(pieces), LONG_TAMIL_WORD)
        for piece in pieces:
            self.assertLessEqual(len(piece), 5)
        for a, b in zip(pieces, pieces[1:]):
            self.assertEqual(unicodedata.combining(b[0]), 0)      # the mark stayed with its letter


class TestTextTrack(unittest.TestCase):
    CUES = [{"text": "First line", "start": 0.0, "end": 1.5},
            {"text": "Second\nline", "start": 1.5, "end": 3.0}]

    def test_items_follow_the_caption_style(self):
        items = captions.to_text_track(self.CUES, {"font": "Poppins", "size": 40, "weight": 700, "y": 0.9, "bg": "#000000AA"})
        self.assertEqual([i["id"] for i in items], ["cap1", "cap2"])
        self.assertEqual((items[0]["font"], items[0]["size"], items[0]["weight"], items[0]["y"]), ("Poppins", 40.0, 700, 0.9))
        self.assertEqual(items[0]["bg"], "#000000")                # the alpha is dropped
        self.assertEqual(items[0]["text"], "First line")

    def test_a_font_without_that_weight_falls_back(self):
        items = captions.to_text_track(self.CUES, {"font": "Anton", "weight": 700})
        self.assertEqual(items[0]["font"], "Anton")
        self.assertIn(items[0]["weight"], editor.FONTS["Anton"]["weights"])

    def test_an_unknown_font_falls_back_to_a_bundled_one(self):
        items = captions.to_text_track(self.CUES, {"font": "Comic Sans"})
        self.assertIn(items[0]["font"], editor.FONTS)

    def test_the_items_pass_the_editor(self):
        items = captions.to_text_track(self.CUES)
        doc = editor.clean({"tracks": {"text": items}})
        self.assertEqual(doc["tracks"]["text"], items)

    def test_with_captions_returns_a_valid_edit(self):
        edit = editor.clean({"tracks": {"video": [{"id": "v1", "src": "clips/a.mp4", "in": 0, "out": 2}]}})
        out = captions.with_captions(edit, self.CUES, {"size": 40})
        self.assertEqual(len(out["tracks"]["text"]), 2)
        self.assertEqual(len(edit["tracks"]["text"]), 0)           # the caller's edit is untouched

    def test_the_style_comes_from_a_format(self):
        style = captions.style_from_format("instagram-reel")
        self.assertEqual(style["font"], "Poppins")
        items = captions.to_text_track(self.CUES, style)
        self.assertEqual((items[0]["font"], items[0]["size"], items[0]["weight"], items[0]["y"]), ("Poppins", 40.0, 700, 0.72))
        self.assertEqual(items[0]["bg"], "#000000")                # the format's alpha is dropped

    def test_the_style_comes_from_a_brand_kit(self):
        kit = {"caption": {"font": "Pacifico", "size": 32, "weight": 400, "y": 0.8, "bg": "#101010"}}
        self.assertEqual(captions.style_from_kit(kit)["font"], "Pacifico")
        items = captions.to_text_track(self.CUES, captions.style_from_kit(kit))
        self.assertEqual((items[0]["font"], items[0]["size"], items[0]["bg"]), ("Pacifico", 32.0, "#101010"))


class TestVoiceoverPlacement(unittest.TestCase):
    def edit(self):
        return editor.clean({"tracks": {"video": [
            {"id": "s01", "src": "clips/a.mp4", "in": 0, "out": 4, "volume": 1, "transition": {"type": "cut", "dur": 0.5}},
            {"id": "s02", "src": "clips/b.mp4", "in": 0, "out": 4, "volume": 1, "transition": {"type": "cut", "dur": 0.5}}]}})

    def test_a_short_voiceover_fits_without_a_warning(self):
        res = captions.place_voiceover(self.edit(), "s01", "audio/vo/s01.mp3", 3.0)
        self.assertEqual(res["warnings"], [])
        self.assertEqual(res["speed"], 1.0)
        self.assertTrue(res["fits"])
        clip = res["patch"]["tracks"]["audio"][0]
        self.assertEqual((clip["id"], clip["src"], clip["start"]), ("vo_s01", "audio/vo/s01.mp3", 0.0))
        self.assertAlmostEqual(clip["out"], 3.0)

    def test_the_second_shot_starts_after_the_first(self):
        res = captions.place_voiceover(self.edit(), "s02", "audio/vo/s02.mp3", 3.0)
        self.assertAlmostEqual(res["patch"]["tracks"]["audio"][0]["start"], 4.0)

    def test_a_longer_voiceover_is_sped_up_within_twelve_percent(self):
        res = captions.place_voiceover(self.edit(), "s01", "audio/vo/s01.mp3", 4.2)
        self.assertTrue(res["fits"])
        self.assertAlmostEqual(res["speed"], 1.05, places=3)
        self.assertIn("sped up", res["warnings"][0])

    def test_a_much_longer_voiceover_is_reported_as_too_long(self):
        res = captions.place_voiceover(self.edit(), "s01", "audio/vo/s01.mp3", 8.0)
        self.assertFalse(res["fits"])
        self.assertEqual(res["speed"], 1.0)
        self.assertIn("speech too long for the clip", res["warnings"][0])

    def test_an_unknown_shot_and_a_bad_path_are_refused(self):
        with self.assertRaises(ValueError):
            captions.place_voiceover(self.edit(), "s09", "audio/vo/s09.mp3", 2.0)
        with self.assertRaises(editor.EditError):
            captions.place_voiceover(self.edit(), "s01", "../escape.mp3", 2.0)

    def test_the_patch_can_be_applied_to_the_edit(self):
        res = captions.place_voiceover(self.edit(), "s01", "audio/vo/s01.mp3", 3.0)
        out = editor.clean(captions.apply_patch(self.edit(), res["patch"]))
        self.assertEqual([a["id"] for a in out["tracks"]["audio"]], ["vo_s01"])


class TestPreview(unittest.TestCase):
    def setUp(self):
        self.p = Path(tempfile.mkdtemp())
        (self.p / "shots.json").write_text(json.dumps({"shots": [
            {"id": "s01", "seconds": 4, "voice_mode": "off-camera", "voice_line": "கடையில் பால் விற்கிறார்கள்", "english": "They sell milk in the shop"},
            {"id": "s02", "seconds": 3, "voice_mode": "silent", "voice_line": "", "english": ""}]}), encoding="utf-8")

    def test_the_voice_line_becomes_cues(self):
        out = captions.preview(self.p, "s01")
        self.assertEqual(out["source"], "voice_line")
        self.assertEqual(out["script"], "கடையில் பால் விற்கிறார்கள்")
        self.assertTrue(out["cues"])
        self.assertAlmostEqual(out["cues"][0]["start"], 0.0)
        self.assertAlmostEqual(out["cues"][-1]["end"], 4.0)

    def test_the_english_gloss_is_the_fallback(self):
        (self.p / "shots.json").write_text(json.dumps({"shots": [{"id": "s03", "seconds": 2, "voice_line": "", "english": "Hello there"}]}), encoding="utf-8")
        out = captions.preview(self.p, "s03")
        self.assertEqual(out["source"], "english")
        self.assertEqual(" ".join(c["text"] for c in out["cues"]), "Hello there")

    def test_a_silent_shot_has_no_cues(self):
        out = captions.preview(self.p, "s02")
        self.assertEqual(out["cues"], [])

    def test_the_story_is_the_fallback_source(self):
        (self.p / "shots.json").write_text(json.dumps({"shots": [{"id": "s04", "seconds": 2}]}), encoding="utf-8")
        story = ("# Demo: a story\n"
                 "\n"
                 "## Shot 04 — 0:00–0:02\n"
                 "### Purpose: HOOK\n"
                 "**Visual**\nA shop\n"
                 "**Voice** (OFF-CAMERA)\nThe shop is open\n"
                 "**English**\nThe shop is open\n")
        (self.p / "Story.md").write_text(story, encoding="utf-8")
        out = captions.preview(self.p, "s04")
        self.assertEqual(out["source"], "voice_line")
        self.assertEqual(out["script"], "The shop is open")

    def test_preview_writes_nothing(self):
        before = sorted(p.name for p in self.p.iterdir())
        captions.preview(self.p, "s01")
        self.assertEqual(sorted(p.name for p in self.p.iterdir()), before)


try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    HAVE_API = True
except Exception:
    HAVE_API = False
H = {"x-aistudio-token": "tok"}


class TestPreviewRoute(unittest.TestCase):
    @unittest.skipUnless(HAVE_API, "needs the venv with fastapi + httpx")
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.c = TestClient(create_app(self.root, token="tok", static_dir="/nonexistent"))
        self.call("post", "/api/projects", json={"name": "demo"})
        self.call("put", "/api/projects/demo/shots", json={"aspect_ratio": "9:16", "audio": False, "shots": [
            {"id": "s01", "model": "m", "seconds": 4, "prompt": "p", "voice_mode": "off-camera",
             "voice_line": "The shop opens at seven", "english": "The shop opens at seven"},
            {"id": "s02", "model": "m", "seconds": 3, "prompt": "p", "voice_mode": "silent",
             "voice_line": "", "english": ""}]})

    def call(self, m, url, **kw):
        return self.c.request(m.upper(), url, headers=H, **kw)

    def test_the_preview_returns_the_cues_of_the_shot(self):
        r = self.call("get", "/api/projects/demo/captions/preview?shot=s01")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["shot"], "s01")
        self.assertEqual(body["source"], "voice_line")
        self.assertEqual(body["script"], "The shop opens at seven")
        self.assertTrue(body["cues"])
        self.assertAlmostEqual(body["cues"][0]["start"], 0.0)
        self.assertAlmostEqual(body["cues"][-1]["end"], 4.0)

    def test_a_silent_shot_has_no_cues(self):
        body = self.call("get", "/api/projects/demo/captions/preview?shot=s02").json()
        self.assertEqual(body["cues"], [])

    def test_the_line_limits_can_be_set(self):
        body = self.call("get", "/api/projects/demo/captions/preview?shot=s01&max_chars=12&max_lines=1").json()
        for cue in body["cues"]:
            self.assertEqual(len(cue["text"].split("\n")), 1)
            self.assertLessEqual(len(cue["text"]), 12)

    def test_a_missing_shot_or_project_is_refused(self):
        self.assertEqual(self.call("get", "/api/projects/demo/captions/preview").status_code, 400)
        self.assertEqual(self.call("get", "/api/projects/demo/captions/preview?shot=").status_code, 400)
        self.assertEqual(self.call("get", "/api/projects/nope/captions/preview?shot=s01").status_code, 400)

    def test_the_token_is_needed(self):
        self.assertEqual(self.c.get("/api/projects/demo/captions/preview?shot=s01").status_code, 401)

    def test_the_route_is_described_in_the_api_reference(self):
        from server import api_docs
        self.assertEqual(api_docs.undocumented(self.c.app), [])
        self.assertTrue(api_docs.agent_allowed("GET", "/api/projects/{name}/captions/preview"))


if __name__ == "__main__":
    unittest.main()
