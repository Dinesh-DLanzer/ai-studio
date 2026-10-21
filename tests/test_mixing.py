import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import tests._hermetic  # noqa: F401
from aistudio import editor, mixing

FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def make_clip(path, secs=2.0, color="red", audio=True):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s=320x240:r=24:d={secs}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={secs}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"] + (["-c:a", "aac", "-shortest"] if audio else []) + [str(path)]
    subprocess.run(cmd, check=True)


class TestLoudnessArgs(unittest.TestCase):
    def test_the_two_passes_are_exact(self):
        args = mixing.loudness_args(-14)
        self.assertEqual(args["measure"], "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json")
        self.assertEqual(args["apply"], "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=summary")

    def test_the_apply_pass_carries_the_measured_numbers(self):
        measured = {"input_i": "-23.44", "input_tp": "-6.19", "input_lra": "4.30",
                    "input_thresh": "-33.15", "target_offset": "0.3"}
        chain = mixing.loudness_args(-14, measured)["apply"]
        self.assertEqual(chain, "loudnorm=I=-14:TP=-1.5:LRA=11:measured_I=-23.44:measured_TP=-6.19:"
                                "measured_LRA=4.30:measured_thresh=-33.15:offset=0.3:linear=true:print_format=summary")

    def test_another_target(self):
        self.assertEqual(mixing.loudness_args(-23)["measure"], "loudnorm=I=-23:TP=-1.5:LRA=11:print_format=json")
        self.assertEqual(mixing.loudness_args(-16.5)["measure"], "loudnorm=I=-16.5:TP=-1.5:LRA=11:print_format=json")

    def test_a_bad_target_is_refused(self):
        for bad in (0, -80, "loud", None):
            with self.assertRaises(mixing.MixError, msg=str(bad)):
                mixing.loudness_args(bad)

    def test_the_commands_are_exact(self):
        self.assertEqual(mixing.measure_cmd("in.mp4", -14),
                         ["ffmpeg", "-hide_banner", "-nostats", "-nostdin", "-i", "in.mp4",
                          "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"])
        self.assertEqual(mixing.apply_cmd("in.mp4", "out.mp4", -14),
                         ["ffmpeg", "-y", "-hide_banner", "-nostats", "-nostdin", "-i", "in.mp4",
                          "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=summary",
                          "-ar", "48000", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "out.mp4"])

    def test_the_one_pass_filter(self):
        self.assertEqual(mixing.loudnorm_filter(-14), "loudnorm=I=-14:TP=-1.5:LRA=11")

    def test_the_target_of_a_format(self):
        self.assertEqual(mixing.loudness_for_format("instagram-reel"), -14)
        self.assertIsNone(mixing.loudness_for_format("no-such-format"))


class TestParseLoudnorm(unittest.TestCase):
    TEXT = ('[Parsed_loudnorm_0 @ 0x7f8] \n{\n\t"input_i" : "-23.44",\n\t"input_tp" : "-6.19",\n'
            '\t"input_lra" : "4.30",\n\t"input_thresh" : "-33.15",\n\t"output_i" : "-14.02",\n'
            '\t"target_offset" : "0.30"\n}\n')

    def test_the_json_block_is_found(self):
        doc = mixing.parse_loudnorm(self.TEXT)
        self.assertEqual(doc["input_i"], "-23.44")
        self.assertEqual(doc["input_tresh"] if "input_tresh" in doc else doc["input_thresh"], "-33.15")
        self.assertEqual(doc["target_offset"], "0.30")

    def test_no_json_gives_nothing(self):
        self.assertEqual(mixing.parse_loudnorm(""), {})
        self.assertEqual(mixing.parse_loudnorm("ffmpeg said no"), {})
        self.assertEqual(mixing.parse_loudnorm("{not json}"), {})


class TestFilters(unittest.TestCase):
    def test_the_duck_filter(self):
        self.assertEqual(mixing.duck_filter("voice", "music"),
                         "[music][voice]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=300[ducked]")

    def test_the_duck_filter_with_labels_and_an_output(self):
        self.assertEqual(mixing.duck_filter("[vsc3]", "[m4]", out="[dk4]"),
                         "[m4][vsc3]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=300[dk4]")

    def test_the_duck_filter_settings(self):
        self.assertEqual(mixing.duck_filter("v", "m", threshold=0.1, ratio=12, attack=5, release=100),
                         "[m][v]sidechaincompress=threshold=0.1:ratio=12:attack=5:release=100[ducked]")

    def test_the_denoise_filter(self):
        self.assertEqual(mixing.denoise_filter(), "afftdn=nr=12:nf=-25")
        self.assertEqual(mixing.denoise_filter(6, -30), "afftdn=nr=6:nf=-30")


class TestEditorOptions(unittest.TestCase):
    def edit(self):
        return editor.clean({"tracks": {
            "video": [{"id": "s01", "src": "clips/a.mp4", "in": 0, "out": 4, "volume": 1, "transition": {"type": "cut", "dur": 0.5}}],
            "audio": [{"id": "vo_s01", "src": "audio/vo_s01.mp3", "start": 0, "in": 0, "out": 4, "volume": 1, "name": "voiceover s01"},
                      {"id": "m1", "src": "audio/bg.mp3", "start": 0, "in": 0, "out": 4, "volume": 0.4, "name": "music"}]}})

    def plan(self, options=None, doc=None):
        e = doc or self.edit()
        files = {i["src"]: Path("/p") / i["src"] for i in e["tracks"]["video"] + e["tracks"]["audio"]}
        probes = {i["src"]: {"duration": 99, "audio": True} for i in e["tracks"]["video"]}
        return editor.plan(e, files, probes, {}, {}, options=options)

    def fc(self, pl):
        return pl["args"][pl["args"].index("-filter_complex") + 1]

    def test_without_options_the_chain_is_unchanged(self):
        fc = self.fc(self.plan())
        for never in ("sidechaincompress", "afftdn", "loudnorm", "atempo", "asplit"):
            self.assertNotIn(never, fc)

    def test_the_music_ducks_under_the_voiceover(self):
        fc = self.fc(self.plan(options={"duck": True}))
        self.assertIn("sidechaincompress=threshold=0.05:ratio=8:attack=20:release=300", fc)
        self.assertIn("asplit=2", fc)
        self.assertIn("amix=inputs=3", fc)              # the clip, the voice and the ducked music

    def test_the_ducking_can_be_named(self):
        fc = self.fc(self.plan(options={"duck": {"voice": "vo_s01", "music": "m1"}}))
        self.assertIn("sidechaincompress", fc)

    def test_the_denoise_cleans_the_voice(self):
        fc = self.fc(self.plan(options={"duck": True, "denoise": True}))
        self.assertIn("afftdn=nr=12:nf=-25", fc)

    def test_a_sped_up_voiceover_gets_atempo(self):
        doc = self.edit()
        doc["tracks"]["audio"][0]["speed"] = 1.05
        fc = self.fc(self.plan(doc=doc))
        self.assertIn("atempo=1.0500", fc)

    def test_the_options_come_from_the_edit_document(self):
        self.assertEqual(editor.mix_options({"audio": {"loudness": -14, "duck": True}}), {"loudness": -14.0, "duck": True})
        self.assertEqual(editor.mix_options({"mix": {"denoise": True}}), {"denoise": True})
        self.assertEqual(editor.mix_options({}), {})
        self.assertEqual(editor.mix_options({"audio": {"loudness": 3}}), {})       # nonsense is ignored

    def test_the_options_survive_the_save_of_the_edit(self):
        from aistudio.service import Workspace
        ws = Workspace(tempfile.mkdtemp())
        ws.create_project("demo")
        doc = self.edit()
        doc["audio"] = {"loudness": -14, "duck": True}
        ws.edit_put("demo", doc)
        raw = json.loads((ws.pdir("demo") / "edit.json").read_text(encoding="utf-8"))
        self.assertEqual(editor.mix_options(raw), {"loudness": -14.0, "duck": True})


@unittest.skipUnless(FF, "needs ffmpeg")
class TestRealFfmpeg(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.tone = self.tmp / "tone.mp4"
        make_clip(self.tone, 2.0, "red", audio=True)

    def test_a_tone_is_measured(self):
        measured = mixing.loudness_of(self.tone)
        self.assertIn("input_i", measured)
        self.assertLess(float(measured["input_i"]), 0.0)

    def test_the_two_pass_normalises_to_the_target(self):
        out = self.tmp / "loud.mp4"
        res = mixing.normalise(self.tone, out, -14, pdir=self.tmp)
        self.assertTrue(out.is_file())
        self.assertIn("input_i", res["measured"])
        after = mixing.loudness_of(out)
        self.assertAlmostEqual(float(after["input_i"]), -14.0, delta=1.5)

    def test_a_file_outside_the_project_is_refused(self):
        outside = Path(tempfile.mkdtemp()) / "x.mp4"
        outside.write_bytes(b"x")
        with self.assertRaises(mixing.MixError):
            mixing.normalise(outside, self.tmp / "y.mp4", -14, pdir=self.tmp)

    def test_the_export_measures_about_the_target(self):
        """A render with the loudness option measures about -14 LUFS; without it, the mix is left alone."""
        p = Path(tempfile.mkdtemp()) / "demo"
        (p / "clips").mkdir(parents=True)
        (p / "audio").mkdir()
        make_clip(p / "clips" / "a.mp4", 2.0, "red")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=880:duration=2",
                        "-af", "volume=-20dB", str(p / "audio" / "bg.mp3")], check=True)
        doc = editor.clean({"tracks": {
            "video": [{"id": "s01", "src": "clips/a.mp4", "in": 0, "out": 2, "volume": 1, "transition": {"type": "cut", "dur": 0.5}}],
            "audio": [{"id": "m1", "src": "audio/bg.mp3", "start": 0, "in": 0, "out": 2, "volume": 0.6, "name": "music"}]}})
        plain = editor.render(p, doc)
        loud = editor.render(p, doc, options={"loudness": -14})
        self.assertAlmostEqual(float(mixing.loudness_of(p / loud)["input_i"]), -14.0, delta=1.5)
        self.assertNotAlmostEqual(float(mixing.loudness_of(p / plain)["input_i"]), -14.0, delta=1.5)

    def test_the_ducking_and_the_denoise_render(self):
        """The sidechain graph has to be a real ffmpeg graph, not only a string."""
        p = Path(tempfile.mkdtemp()) / "demo"
        (p / "clips").mkdir(parents=True)
        (p / "audio").mkdir()
        make_clip(p / "clips" / "a.mp4", 2.0, "red")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=880:duration=2",
                        str(p / "audio" / "vo.mp3")], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=2",
                        str(p / "audio" / "bg.mp3")], check=True)
        doc = editor.clean({"tracks": {
            "video": [{"id": "s01", "src": "clips/a.mp4", "in": 0, "out": 2, "volume": 1, "transition": {"type": "cut", "dur": 0.5}}],
            "audio": [{"id": "vo_s01", "src": "audio/vo.mp3", "start": 0, "in": 0, "out": 2, "volume": 1, "name": "voiceover s01"},
                      {"id": "m1", "src": "audio/bg.mp3", "start": 0, "in": 0, "out": 2, "volume": 0.4, "name": "music"}]}})
        out = editor.render(p, doc, options={"duck": True, "denoise": True})
        self.assertTrue((p / out).is_file())
        self.assertGreater((p / out).stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
