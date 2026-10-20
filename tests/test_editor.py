import os
import tests._hermetic  # noqa: F401
import json, shutil, subprocess, tempfile, time, unittest, zipfile
from pathlib import Path
from aistudio import editor, trash
from aistudio.service import ServiceError, Workspace

try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    HAVE_API = True
except Exception:
    HAVE_API = False
FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
try:
    import PIL  # noqa: F401
    PILOK = True
except ImportError:
    PILOK = False
H = {"x-aistudio-token": "tok"}


def make_clip(path, secs=2.0, color="red", audio=True):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s=320x240:r=24:d={secs}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={secs}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"] + (["-c:a", "aac", "-shortest"] if audio else []) + [str(path)]
    subprocess.run(cmd, check=True)


def vid(i, src="clips/a.mp4", a=0, b=2, tr="cut", dur=0.5):
    return {"id": i, "src": src, "in": a, "out": b, "volume": 1, "transition": {"type": tr, "dur": dur}}


class TestClean(unittest.TestCase):
    def test_defaults_and_ranges(self):
        d = editor.clean({"tracks": {"video": [vid("v1")], "text": [{"id": "t1", "text": "Hi", "start": 0, "end": 2}]}})
        t = d["tracks"]["text"][0]
        self.assertEqual((d["aspect"], d["fps"], t["font"], t["align"], t["bold"]), ("9:16", 24, "Poppins", "center", True))
        self.assertFalse(t["shadow"]["on"])

    def test_bad_inputs(self):
        bad = [
            {"aspect": "4:3"}, {"fps": 60}, {"tracks": {"video": [vid("v1", src="../x.mp4")]}}, {"tracks": {"video": [vid("v1", src="/etc/x.mp4")]}},
            {"tracks": {"video": [vid("v1", src="clips/_discarded/a.mp4")]}}, {"tracks": {"video": [vid("v1", src="stills/a.png")]}},
            {"tracks": {"video": [vid("v1", a=2, b=2.1)]}}, {"tracks": {"video": [vid("v1"), vid("v1")]}},
            {"tracks": {"video": [vid("v1", tr="spin")]}}, {"tracks": {"video": [vid("v1", tr="wipeleft")]}}, {"tracks": {"text": [{"id": "t", "text": "x" * 101, "start": 0, "end": 2}]}},
            {"tracks": {"text": [{"id": "t", "text": "x", "start": 3, "end": 2}]}}, {"tracks": {"text": [{"id": "t", "text": "x", "start": 0, "end": 2, "color": "red"}]}},
            {"tracks": {"text": [{"id": "t", "text": "x", "start": 0, "end": 2, "font": "Comic"}]}}, {"tracks": {"text": [{"id": "t", "text": "x", "start": 0, "end": 2, "x": 2}]}},
            {"tracks": {"audio": [{"id": "a", "src": "clips/a.mp4", "in": 0, "out": 2}]}}, {"tracks": {"text": [{"id": "t", "text": "  ", "start": 0, "end": 2}]}},
            {"tracks": {"video": [dict(vid("v1"), volume=True)]}}, {"tracks": {"video": [dict(vid("v1"), **{"in": float("nan")})]}},
        ]
        for doc in bad:
            with self.assertRaises(editor.EditError, msg=str(doc)[:80]):
                editor.clean(doc)

    def test_timeline_length_overlaps_transitions(self):
        v = editor.clean({"tracks": {"video": [vid("a", b=4), vid("b", b=4, tr="crossfade", dur=1), vid("c", b=4)]}})["tracks"]["video"]
        self.assertAlmostEqual(editor.timeline_length(v), 11.0)
        v = editor.clean({"tracks": {"video": [vid("a", b=1), vid("b", b=1, tr="fade", dur=2)]}})["tracks"]["video"]
        self.assertAlmostEqual(editor.timeline_length(v), 2 - 0.95)       # clamped so it never exceeds either clip

    def test_elements_clean(self):
        d = editor.clean({"tracks": {"video": [vid("v1")], "elements": [{"id": "e1", "src": "elements/logo.png", "start": 0, "end": 2, "scale": 0.4, "opacity": 0.8}]}})
        el = d["tracks"]["elements"][0]
        self.assertEqual((el["id"], el["src"], el["scale"], el["opacity"], el["x"], el["y"]), ("e1", "elements/logo.png", 0.4, 0.8, 0.5, 0.5))

    def test_transition_options(self):
        doc = {"tracks": {"video": [
            vid("v1", b=4),
            {"id": "v2", "src": "clips/b.mp4", "in": 0, "out": 4, "volume": 1,
             "transition": {"type": "wipe", "dur": 1.2, "direction": "right"}},
            {"id": "v3", "src": "clips/c.mp4", "in": 0, "out": 4, "volume": 1,
             "transition": {"type": "fade", "dur": 0.8, "color": "white"}},
        ]}}
        cl = editor.clean(doc)["tracks"]["video"]
        self.assertEqual(cl[1]["transition"]["direction"], "right")
        self.assertEqual(cl[1]["transition"]["dur"], 1.2)
        self.assertEqual(cl[2]["transition"]["color"], "white")

    def test_look_defaults_and_idempotent(self):
        d = editor.clean({"tracks": {"video": [vid("v1")]}})
        self.assertEqual(d["filter"], {"id": "none", "intensity": 1.0})
        self.assertEqual(d["effect"], {"id": "none", "intensity": 1.0})
        self.assertEqual(d["background"], {"type": "black"})
        self.assertEqual(d["tracks"]["subtitles"]["cues"], [])
        self.assertEqual(d["tracks"]["subtitles"]["style"], "classic")
        self.assertEqual(editor.clean(d), d)                       # clean(clean(x)) == clean(x): put and get agree

    def test_filter_effect_and_background_clean(self):
        d = editor.clean({"filter": "noir", "effect": {"id": "shake", "intensity": 0.5, "speed": 2},
                          "background": {"type": "blur", "blurRadius": 30},
                          "tracks": {"video": [vid("v1")]}})
        self.assertEqual(d["filter"], {"id": "noir", "intensity": 1.0})
        self.assertEqual(d["effect"], {"id": "shake", "intensity": 0.5, "speed": 2.0})
        self.assertEqual(d["background"], {"type": "blur", "blurRadius": 30.0})
        d = editor.clean({"filter": {"id": "warm", "intensity": 0.2},
                          "background": {"type": "color", "color": "#1E1B4B"},
                          "tracks": {"video": [vid("v1")]}})
        self.assertEqual(d["filter"], {"id": "warm", "intensity": 0.2})
        self.assertEqual(d["background"], {"type": "color", "color": "#1e1b4b"})
        d = editor.clean({"background": {"type": "gradient", "gradient": {"from": "#2e0854", "to": "#0f051d"}},
                          "tracks": {"video": [vid("v1")]}})
        self.assertEqual(d["background"]["gradient"], {"from": "#2e0854", "to": "#0f051d"})

    def test_every_filter_and_effect_id_is_known(self):
        self.assertEqual(editor.FILTERS, {"cinema", "teal_orange", "vintage", "noir", "vibrant", "cyberpunk", "warm", "none"})
        self.assertEqual(editor.EFFECTS, {"vignette", "grain", "shake", "zoompulse", "glitch", "blur", "none"})
        for fid in editor.FILTERS:
            self.assertEqual(editor.clean({"filter": {"id": fid}, "tracks": {"video": [vid("v1")]}})["filter"]["id"], fid)
        for eid in editor.EFFECTS:
            self.assertEqual(editor.clean({"effect": {"id": eid}, "tracks": {"video": [vid("v1")]}})["effect"]["id"], eid)

    def test_look_bad_values_refused(self):
        bad = [
            {"filter": {"id": "sepia"}}, {"filter": {"id": "noir", "intensity": 4}}, {"filter": 7},
            {"effect": {"id": "spin"}}, {"effect": {"id": "shake", "speed": 0}}, {"effect": ["shake"]},
            {"background": {"type": "square"}}, {"background": {"type": "color", "color": "red"}},
            {"background": {"type": "gradient"}}, {"background": {"type": "gradient", "gradient": {"from": "#112233"}}},
            {"tracks": {"video": [vid("v1")], "subtitles": {"style": "neon"}}},
            {"tracks": {"video": [vid("v1")], "subtitles": {"font": "Comic"}}},
            {"tracks": {"video": [vid("v1")], "subtitles": {"cues": [{"id": "c1", "start": 0, "end": 0, "text": "x"}]}}},
            {"tracks": {"video": [vid("v1")], "subtitles": {"cues": [{"id": "c1", "start": 0, "end": 1, "text": "  "}]}}},
            {"tracks": {"video": [vid("v1")], "subtitles": {"cues": [{"id": "c1", "start": 0, "end": 1, "text": "x" * 201}]}}},
            {"tracks": {"video": [vid("v1")], "subtitles": {"cues": [{"id": "c1", "start": 0, "end": 1, "text": "a"},
                                                                      {"id": "c1", "start": 1, "end": 2, "text": "b"}]}}},
            {"tracks": {"video": [vid("v1")], "subtitles": {"cues": [{"start": 0, "end": 1, "text": "x"}, "nope"]}}},
            {"tracks": {"video": [vid("v1")], "subtitles": "captions"}},
        ]
        for doc in bad:
            with self.assertRaises(editor.EditError, msg=str(doc)[:90]):
                editor.clean(doc)

    def test_subtitles_clean(self):
        d = editor.clean({"tracks": {"video": [vid("v1")], "subtitles": {
            "style": "tiktok", "font": "Anton", "size": 40, "color": "#ffe600", "bg": "#000000", "y": 0.9,
            "cues": [{"start": 0, "end": 1.5, "text": "  Look here  "}, {"id": "c2", "start": 1.5, "end": 3, "text": "second\nline"}]}}})
        s = d["tracks"]["subtitles"]
        self.assertEqual((s["style"], s["font"], s["size"], s["color"], s["bg"], s["y"]), ("tiktok", "Anton", 40.0, "#ffe600", "#000000", 0.9))
        self.assertEqual([c["id"] for c in s["cues"]], ["cue1", "c2"])          # a cue without an id gets one
        self.assertEqual(s["cues"][0]["text"], "Look here")                     # trimmed, the timeline keeps the rest
        self.assertEqual(s["cues"][1]["text"], "second\nline")
        # a bare list of cues (an older save) is still accepted
        self.assertEqual(editor.clean({"tracks": {"subtitles": [{"id": "c", "start": 0, "end": 1, "text": "hi"}]}})["tracks"]["subtitles"]["cues"][0]["text"], "hi")

    def test_cues_are_capped(self):
        cues = [{"id": f"c{i}", "start": i, "end": i + 1, "text": "x"} for i in range(editor.MAX_CUES + 1)]
        with self.assertRaises(editor.EditError):
            editor.clean({"tracks": {"subtitles": {"cues": cues}}})



class TestPlan(unittest.TestCase):
    def build(self, doc, pngs=None, audio_in=True, subs=None):
        e = editor.clean(doc)
        files = {i["src"]: Path("/p") / i["src"] for i in e["tracks"]["video"] + e["tracks"]["audio"]}
        probes = {i["src"]: {"duration": 99, "audio": audio_in} for i in e["tracks"]["video"]}
        return editor.plan(e, files, probes, pngs or {}, subs or {})

    def test_cut_xfade_text_music(self):
        doc = {"aspect": "16:9", "tracks": {"video": [vid("a", b=3), vid("b", "clips/b.mp4", b=3, tr="crossfade", dur=1), vid("c", "clips/c.mp4", b=2)],
                "text": [{"id": "t1", "text": "Hi", "start": 1, "end": 4}], "audio": [{"id": "m", "src": "audio/m.mp3", "in": 0, "out": 8, "start": 1, "fadeIn": 1, "fadeOut": 2, "volume": 0.5}]}}
        pl = self.build(doc, {"t1": (Path("/tmp/t1.png"), 200, 100)})
        fc = pl["args"][pl["args"].index("-filter_complex") + 1]
        self.assertAlmostEqual(pl["total"], 7.0)
        for needle in ("scale=1280:720", "xfade=transition=fade:duration=1.000:offset=2.000", "acrossfade=d=1.000", "concat=n=2:v=1:a=0",
                       "overlay=x=540:y=382:enable='between(t,1.000,4.000)'", "afade=t=in", "afade=t=out:st=6.000:d=2.000", "adelay=1000|1000",
                       "amix=inputs=2", "[vout]", "[aout]"):
            self.assertIn(needle, fc)
        self.assertEqual(pl["args"].count("-i"), 5)

    def test_transition_options_plan(self):
        doc = {"tracks": {"video": [
            vid("a", b=3),
            {"id": "b", "src": "clips/b.mp4", "in": 0, "out": 3, "volume": 1,
             "transition": {"type": "wipe", "dur": 1.0, "direction": "right"}},
        ]}}
        pl = self.build(doc)
        fc = pl["args"][pl["args"].index("-filter_complex") + 1]
        self.assertIn("xfade=transition=wiperight:duration=1.000:offset=2.000", fc)

    def test_silent_clip_gets_silence(self):
        pl = self.build({"tracks": {"video": [vid("a")]}}, audio_in=False)
        self.assertIn("anullsrc", pl["args"][pl["args"].index("-filter_complex") + 1])

    def test_empty_refused(self):
        with self.assertRaises(editor.EditError):
            self.build({"tracks": {}})

    @staticmethod
    def fc(pl):
        return pl["args"][pl["args"].index("-filter_complex") + 1]

    def test_grade_effect_background_and_subtitles_in_the_chain(self):
        doc = {"filter": {"id": "noir", "intensity": 1}, "effect": {"id": "vignette"},
               "background": {"type": "color", "color": "#1E1B4B"},
               "tracks": {"video": [vid("a", b=3), vid("b", "clips/b.mp4", b=3, tr="crossfade", dur=1)],
                          "subtitles": {"y": 0.9, "cues": [{"id": "c1", "start": 0, "end": 2, "text": "Hi"}]}}}
        pl = self.build(doc, subs={"c1": (Path("/tmp/c1.png"), 200, 60)})
        fc = self.fc(pl)
        self.assertIn("eq=saturation=0.0000:contrast=1.2500", fc)                      # noir
        self.assertIn("vignette=angle=0.7854", fc)                                      # vignette
        self.assertIn("pad=720:1280:(ow-iw)/2:(oh-ih)/2:color=0x1e1b4b", fc)            # flat colour behind the letterbox
        self.assertIn("xfade=transition=fade:duration=1.000:offset=2.000", fc)          # the look is applied after the join
        self.assertIn(":enable='between(t,0.000,2.000)'", fc)                          # the burned subtitle cue
        self.assertEqual(pl["args"].count("-i"), 3)                                     # two clips + one subtitle PNG

    def test_blur_background_fills_the_frame(self):
        doc = {"background": {"type": "blur", "blurRadius": 40}, "tracks": {"video": [vid("a")]}}
        fc = self.fc(self.build(doc))
        self.assertIn("split=2[fgr0][bgs0]", fc)
        self.assertIn("scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,boxblur=40:2", fc)
        self.assertIn("[bgc0][fgs0]overlay=x=(W-w)/2:y=(H-h)/2", fc)             # the background is the main input: it sets the frame size

    def test_no_look_and_no_subtitles_add_nothing(self):
        fc = self.fc(self.build({"tracks": {"video": [vid("a")]}}))
        for never in ("eq=", "colorbalance=", "vignette=", "noise=", "zoompan=", "rgbashift=", "gblur=", "boxblur=", "between(t,"):
            self.assertNotIn(never, fc)

    def test_every_filter_and_effect_builds_a_chain(self):
        for fid in sorted(editor.FILTERS - {"none"}):
            fc = self.fc(self.build({"filter": {"id": fid, "intensity": 0.7}, "tracks": {"video": [vid("a")]}}))
            self.assertTrue("eq=" in fc or "colorbalance=" in fc, fid)
        for eid, needle in (("vignette", "vignette=angle="), ("grain", "noise=alls="), ("shake", "crop=iw-"),
                            ("zoompulse", "zoompan=z="), ("glitch", "rgbashift="), ("blur", "gblur=sigma=")):
            fc = self.fc(self.build({"effect": {"id": eid, "intensity": 0.6}, "tracks": {"video": [vid("a")]}}))
            self.assertIn(needle, fc, eid)


@unittest.skipUnless(PILOK, "needs Pillow")
class TestTextPng(unittest.TestCase):
    def test_png_renders_with_bubble_shadow(self):
        from PIL import Image
        t = editor.clean({"tracks": {"text": [{"id": "t", "text": "Turn Ideas into\nStunning Videos", "start": 0, "end": 2, "bg": "#9b30ff", "underline": True,
                                              "shadow": {"on": True, "blur": 20}, "opacity": 0.8, "caps": True, "align": "left"}]}})["tracks"]["text"][0]
        f = Path(tempfile.mkdtemp()) / "t.png"
        w, h = editor.render_text_png(t, 720, f)
        im = Image.open(f)
        self.assertEqual(im.size, (w, h))
        self.assertTrue(im.getchannel("A").getextrema()[1] > 0)
        self.assertLess(im.getchannel("A").getextrema()[1], 256)


class TestCaptions(unittest.TestCase):
    CUES = {"style": "classic", "cues": [
        {"id": "c1", "start": 0, "end": 1.5, "text": "First line"},
        {"id": "c2", "start": 61.25, "end": 65, "text": "Second\nline"}]}

    def test_srt(self):
        self.assertEqual(editor.export_srt(self.CUES),
                         "1\n00:00:00,000 --> 00:00:01,500\nFirst line\n\n"
                         "2\n00:01:01,250 --> 00:01:05,000\nSecond\nline\n")

    def test_vtt(self):
        v = editor.export_vtt(self.CUES)
        self.assertTrue(v.startswith("WEBVTT\n\n"))
        self.assertIn("1\n00:00:00.000 --> 00:00:01.500\nFirst line", v)
        self.assertIn("2\n00:01:01.250 --> 00:01:05.000", v)

    def test_empty_and_bare_cues(self):
        self.assertEqual(editor.export_srt([]), "")
        self.assertEqual(editor.export_vtt([]), "WEBVTT\n\n")
        self.assertIn("First line", editor.export_srt(self.CUES["cues"]))      # a plain list works too


class TestNleExport(unittest.TestCase):
    def doc(self):
        return editor.clean({"aspect": "16:9", "fps": 25, "tracks": {
            "video": [vid("v1", b=4),
                      {"id": "v2", "src": "clips/b.mp4", "in": 1, "out": 5, "volume": 1, "transition": {"type": "crossfade", "dur": 1}}],
            "audio": [{"id": "m", "src": "audio/m.mp3", "start": 2, "in": 0, "out": 6, "volume": 0.5, "fadeIn": 0, "fadeOut": 0, "name": "music"}],
            "subtitles": {"cues": [{"id": "c1", "start": 0, "end": 2, "text": "Hello"}]}}})

    @staticmethod
    def files(d):
        return {i["src"]: Path("/proj/demo") / i["src"] for i in d["tracks"]["video"] + d["tracks"]["audio"]}

    def test_fcpxml_parses_and_carries_the_timeline(self):
        import xml.etree.ElementTree as ET
        d = self.doc()
        x = editor.export_fcpxml(d, self.files(d), {})
        root = ET.fromstring(x)
        self.assertEqual((root.tag, root.get("version")), ("fcpxml", "1.9"))
        assets = {a.get("name"): a for a in root.iter("asset")}
        self.assertEqual(set(assets), {"a.mp4", "b.mp4", "m.mp3"})
        self.assertEqual(assets["a.mp4"].get("src"), "file:///proj/demo/clips/a.mp4")
        self.assertEqual(assets["a.mp4"].get("format"), "rf1")                  # one media format resource for 1280x720
        clips = list(root.iter("asset-clip"))
        self.assertEqual(len(clips), 3)
        self.assertEqual([c.get("offset") for c in clips], ["0/25s", "75/25s", "50/25s"])
        self.assertEqual([c.get("duration") for c in clips], ["100/25s", "100/25s", "150/25s"])
        self.assertEqual(clips[1].get("start"), "25/25s")                      # clip 2 starts one second into its file
        tr = clips[1].find("transition")                                       # the crossfade lands as a dissolve
        self.assertIsNotNone(tr)
        self.assertEqual((tr.get("outgoingDuration"), tr.get("incomingDuration")), ("25/25s", "25/25s"))
        self.assertEqual(clips[2].get("lane"), "-1")                           # music below the picture
        self.assertEqual(clips[2].get("role"), "music")
        self.assertIn('event name="demo"', x)
        self.assertEqual(root.find(".//sequence").get("duration"), "175/25s")  # 4 s + 4 s - 1 s dissolve = 7 s

    def test_fcpxml_needs_a_clip(self):
        with self.assertRaises(editor.EditError):
            editor.export_fcpxml(editor.clean({"tracks": {}}), {}, {})

    def test_edl_columns_and_dissolve(self):
        d = self.doc()
        e = editor.export_edl(d, self.files(d))
        lines = e.splitlines()
        self.assertEqual(lines[:2], ["TITLE: demo", "FCM: NON-DROP FRAME"])
        ev = [l.split() for l in lines if l[:3].isdigit()]
        self.assertEqual(len(ev), 3)                                           # two picture events + the music
        self.assertEqual(ev[0][:6], ["001", "A", "V", "C", "00:00:00:00", "00:00:04:00"])
        self.assertEqual(ev[0][6:], ["00:00:00:00", "00:00:04:00"])
        self.assertEqual(ev[1][:4], ["002", "B", "V", "D"])                    # D = dissolve into this event
        self.assertEqual(ev[1][6:], ["00:00:03:00", "00:00:07:00"])            # record-in overlaps the previous record-out by 1 s
        self.assertEqual(ev[2][:4], ["003", "M", "A1", "C"])
        self.assertEqual(ev[2][4:], ["00:00:00:00", "00:00:06:00", "00:00:02:00", "00:00:08:00"])
        self.assertIn("* TRANSITION IN: DISSOLVE DURATION 00:00:01:00", e)
        self.assertIn("* SOURCE FILE: clips/a.mp4", e)
        self.assertTrue(e.endswith("\n"))

    def test_edl_needs_a_clip(self):
        with self.assertRaises(editor.EditError):
            editor.export_edl(editor.clean({"tracks": {}}), {})


class TestBundle(unittest.TestCase):
    def setUp(self):
        self.p = Path(tempfile.mkdtemp()) / "demo"
        (self.p / "clips").mkdir(parents=True)
        (self.p / "audio").mkdir()
        (self.p / "exports").mkdir()
        for rel, data in (("clips/a.mp4", b"aaa"), ("clips/b.mp4", b"bbb"), ("audio/m.mp3", b"mmm"),
                          ("exports/demo_1.mp4", b"preview")):
            (self.p / rel).write_bytes(data)
        self.doc = editor.clean({"aspect": "16:9", "tracks": {
            "video": [vid("v1"), {"id": "v2", "src": "clips/b.mp4", "in": 0, "out": 2, "volume": 1, "transition": {"type": "crossfade", "dur": 0.5}},
                      {"id": "v3", "src": "clips/gone.mp4", "in": 0, "out": 2, "volume": 1, "transition": {"type": "cut", "dur": 0.5}}],
            "audio": [{"id": "m", "src": "audio/m.mp3", "start": 1, "in": 0, "out": 3, "volume": 0.6, "fadeIn": 0, "fadeOut": 0, "name": "music"}],
            "subtitles": {"cues": [{"id": "c1", "start": 0, "end": 1.5, "text": "Hello"}]}}})
        self.files, _ = editor.media(self.p, self.doc)

    def test_bundle_holds_media_captions_nle_and_preview(self):
        import xml.etree.ElementTree as ET
        z = editor.export_bundle(self.p, self.doc, self.files)
        with zipfile.ZipFile(z) as b:
            names = b.namelist()
            self.assertIn("clips/a.mp4", names)
            self.assertIn("audio/m.mp3", names)
            self.assertNotIn("clips/gone.mp4", names)                          # a missing file is skipped, not an error
            self.assertEqual(b.read("clips/a.mp4"), b"aaa")
            self.assertEqual(b.read("captions.srt").decode(), editor.export_srt(self.doc["tracks"]["subtitles"]))
            self.assertTrue(b.read("captions.vtt").startswith(b"WEBVTT"))
            self.assertEqual(b.read("storyboard_guide.mp4"), b"preview")       # newest render as the guide
            self.assertIn("timeline.edl", names)
            ET.fromstring(b.read("timeline.fcpxml"))
            summary = json.loads(b.read("timeline_summary.json"))
        self.assertEqual((summary["aspect"], summary["fps"]), ("16:9", 24))
        self.assertEqual(summary["duration"], 5.5)                             # 2 + 2 + 2 - 0.5 dissolve
        self.assertEqual([c["src"] for c in summary["clips"]], ["clips/a.mp4", "clips/b.mp4", "clips/gone.mp4"])
        self.assertEqual(summary["subtitles"], {"style": "classic", "cues": 1})
        self.assertFalse((self.p / "timeline.fcpxml").exists())                # nothing was written into the project
        Path(z).unlink()

    def test_bundle_needs_a_clip(self):
        with self.assertRaises(editor.EditError):
            editor.export_bundle(self.p, editor.clean({"tracks": {}}), {})


@unittest.skipUnless(FF and PILOK, "needs ffmpeg + Pillow")
class TestRender(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(tempfile.mkdtemp())
        self.ws.create_project("demo")
        self.p = self.ws.pdir("demo")
        (self.p / "clips").mkdir(exist_ok=True)
        make_clip(self.p / "clips" / "s01_final_a1.mp4", 2, "red")
        make_clip(self.p / "clips" / "s02_final_a1.mp4", 2, "blue", audio=False)
        self.ws.put_shots("demo", {"aspect_ratio": "9:16", "audio": False, "shots": [
            {"id": "s01", "model": "m", "seconds": 4, "prompt": "p"}, {"id": "s02", "model": "m", "seconds": 4, "prompt": "p"}]})

    def probe(self, rel):
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(self.p / rel)], capture_output=True, text=True)
        return json.loads(r.stdout)

    def test_default_edit_uses_real_durations(self):
        g = self.ws.edit_get("demo")
        v = g["edit"]["tracks"]["video"]
        self.assertEqual([x["src"] for x in v], ["clips/s01_final_a1.mp4", "clips/s02_final_a1.mp4"])
        self.assertAlmostEqual(v[0]["out"], 2.0, delta=0.1)
        self.assertFalse(g["saved"])

    def test_export_with_transition_text_music(self):
        mus = self.p / "audio"
        mus.mkdir()
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=880:duration=5", str(mus / "bg.mp3")], check=True)
        doc = self.ws.edit_get("demo")["edit"]
        doc["tracks"]["video"][1]["transition"] = {"type": "crossfade", "dur": 0.5}
        doc["tracks"]["text"] = [{"id": "t1", "text": "Hello\nWorld", "start": 0.5, "end": 3, "bg": "#9b30ff", "shadow": {"on": True, "blur": 10}}]
        doc["tracks"]["audio"] = [{"id": "m1", "src": "audio/bg.mp3", "in": 0, "out": 4, "volume": 0.5, "fadeIn": 0.5, "fadeOut": 0.5}]
        self.ws.edit_put("demo", doc)
        seen = []
        res = self.ws.edit_export("demo", seen.append)
        info = self.probe(res["file"])
        self.assertAlmostEqual(float(info["format"]["duration"]), 3.5, delta=0.15)
        kinds = {s["codec_type"] for s in info["streams"]}
        self.assertEqual(kinds, {"video", "audio"})
        vs = next(s for s in info["streams"] if s["codec_type"] == "video")
        self.assertEqual((vs["width"], vs["height"]), (720, 1280))
        self.assertTrue(seen and seen[-1] == 100.0)
        # the text frame differs from the same frame of an export without text
        doc["tracks"]["text"] = []
        self.ws.edit_put("demo", doc)
        time.sleep(1.1)
        plain = self.ws.edit_export("demo")["file"]
        fa, fb = self.p / "a.png", self.p / "b.png"
        for rel, out in ((res["file"], fa), (plain, fb)):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.0", "-i", str(self.p / rel), "-frames:v", "1", str(out)], check=True)
        self.assertNotEqual(fa.read_bytes(), fb.read_bytes())
        self.assertEqual(len(self.ws.exports("demo")), 2)

    def test_filter_effect_background_and_subtitles_render(self):
        """One render with every new module active: blurred background fill, noir grade, vignette and two burned subtitle cues."""
        doc = self.ws.edit_get("demo")["edit"]
        doc["filter"] = {"id": "noir", "intensity": 1}
        doc["effect"] = {"id": "vignette", "intensity": 1}
        doc["background"] = {"type": "blur", "blurRadius": 20}
        doc["tracks"]["subtitles"] = {"style": "tiktok", "size": 40, "y": 0.9, "cues": [
            {"id": "c1", "start": 0, "end": 2, "text": "First line"},
            {"id": "c2", "start": 2, "end": 4, "text": "Second line"}]}
        self.ws.edit_put("demo", doc)
        res = self.ws.edit_export("demo")["file"]
        info = self.probe(res)
        self.assertAlmostEqual(float(info["format"]["duration"]), 4.0, delta=0.2)   # two 2 s clips, no transition
        vs = next(s for s in info["streams"] if s["codec_type"] == "video")
        self.assertEqual((vs["width"], vs["height"]), (720, 1280))
        # the same edit without any of it, on a flat colour background: the frame must differ
        doc["filter"], doc["effect"] = {"id": "none"}, {"id": "none"}
        doc["background"] = {"type": "color", "color": "#1e1b4b"}
        doc["tracks"]["subtitles"]["cues"] = []
        self.ws.edit_put("demo", doc)
        time.sleep(1.1)
        plain = self.ws.edit_export("demo")["file"]
        self.assertNotEqual(res, plain)
        fa, fb = self.p / "a.png", self.p / "b.png"
        for rel, out in ((res, fa), (plain, fb)):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.0", "-i", str(self.p / rel), "-frames:v", "1", str(out)], check=True)
        self.assertNotEqual(fa.read_bytes(), fb.read_bytes())

    def test_every_filter_effect_and_background_renders(self):
        """Each id must be a real ffmpeg chain: one short render per preset, and the output keeps its length."""
        cases = ([("filter", i, {"id": i}) for i in sorted(editor.FILTERS - {"none"})]
                 + [("effect", i, {"id": i}) for i in sorted(editor.EFFECTS - {"none"})]
                 + [("background", c["type"], c) for c in ({"type": "black"}, {"type": "blur", "blurRadius": 15},
                                                           {"type": "color", "color": "#123456"},
                                                           {"type": "gradient", "gradient": {"from": "#2e0854", "to": "#0f051d"}})])
        for kind, label, value in cases:
            with self.subTest(kind=kind, id=label):
                doc = self.ws.edit_get("demo")["edit"]
                doc[kind] = value
                doc["tracks"]["video"] = [dict(doc["tracks"]["video"][0], out=1.0)]
                self.ws.edit_put("demo", doc)
                d = float(self.probe(self.ws.edit_export("demo")["file"])["format"]["duration"])
                self.assertAlmostEqual(d, 1.0, delta=0.15)

    def test_every_transition_renders(self):
        """All transition ids map to a real xfade name: one render chains every one of them."""
        ids = [t for t in editor.TRANSITIONS if t != "cut"]
        doc = {"aspect": "1:1", "tracks": {"video": [vid("c0", "clips/s01_final_a1.mp4", 0, 1)] + [vid(f"c{i + 1}", "clips/s0%d_final_a1.mp4" % (1 + (i + 1) % 2), 0, 1, tr=t, dur=0.2) for i, t in enumerate(ids)]}}
        self.ws.edit_put("demo", doc)
        res = self.ws.edit_export("demo")
        d = float(self.probe(res["file"])["format"]["duration"])
        self.assertAlmostEqual(d, 1 + len(ids) * 0.8, delta=0.3)

    def test_missing_clip_and_overlong_clip_refused(self):
        doc = self.ws.edit_get("demo")["edit"]
        doc["tracks"]["video"][0]["out"] = 30
        self.ws.edit_put("demo", doc)
        with self.assertRaises(ServiceError) as cm:
            self.ws.edit_export("demo")
        self.assertIn("only", str(cm.exception))
        (self.p / "clips" / "s02_final_a1.mp4").unlink()
        self.assertEqual(self.ws.edit_get("demo")["missing"], ["s02"])


class TestEditService(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(tempfile.mkdtemp())
        self.ws.create_project("demo")

    def test_put_get_roundtrip_and_bad(self):
        with self.assertRaises(ServiceError):
            self.ws.edit_put("demo", {"aspect": "4:3"})
        d = self.ws.edit_put("demo", {"aspect": "1:1", "tracks": {"video": [vid("a")]}})
        self.assertTrue(self.ws.edit_get("demo")["saved"])
        self.assertEqual(self.ws.edit_get("demo")["edit"], d)

    def test_corrupt_edit_json_falls_back(self):
        (self.ws.pdir("demo") / "edit.json").write_text("{\"aspect\": \"9:99\"}")
        g = self.ws.edit_get("demo")
        self.assertIn("could not be used", g["warning"])

    def test_audio_upload_rules(self):
        with self.assertRaises(ServiceError):
            self.ws.add_audio("demo", "evil.exe", b"x")
        r = self.ws.add_audio("demo", "My Song!.mp3", b"not audio") if not shutil.which("ffprobe") else None
        if r:
            self.assertEqual(r["src"], "audio/My_Song.mp3")
        else:
            with self.assertRaises(ServiceError):
                self.ws.add_audio("demo", "My Song!.mp3", b"not audio")
            self.assertTrue((self.ws.pdir("demo") / "audio" / "My_Song.mp3.rejected").exists())


class TestTrash(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(tempfile.mkdtemp())
        self.ws.create_project("demo")
        p = self.ws.pdir("demo")
        (p / "clips" / "_discarded").mkdir(parents=True)
        (p / "clips" / "a.mp4").write_bytes(b"a")
        (p / "clips" / "_discarded" / "old.mp4").write_bytes(b"old")

    def test_delete_needs_exact_name_and_moves(self):
        with self.assertRaises(ServiceError):
            self.ws.delete_project("demo", "dem")
        self.assertTrue(self.ws.pdir("demo").exists())
        tid = self.ws.delete_project("demo", "demo")["trash"]
        self.assertEqual([x["name"] for x in self.ws.list_projects()], [])
        item = self.ws.trash_list()[0]
        self.assertEqual((item["id"], item["name"]), (tid, "demo"))
        self.assertTrue((Path(self.ws.root) / "_trash" / tid / "clips" / "a.mp4").exists())      # nothing was erased

    def test_restore_and_conflict(self):
        tid = self.ws.delete_project("demo", "demo")["trash"]
        self.ws.create_project("demo")
        with self.assertRaises(ServiceError):
            self.ws.trash_restore(tid)
        self.assertEqual(self.ws.trash_restore(tid, "demo2")["name"], "demo2")
        self.assertTrue((self.ws.pdir("demo2") / "clips" / "a.mp4").exists())
        for bad in ("../x", "nope", ""):
            with self.assertRaises(ServiceError):
                self.ws.trash_restore(bad)

    def test_same_second_twice_keeps_both(self):
        a = trash.move_to_trash(self.ws.root, "demo")
        self.ws.create_project("demo")
        b = trash.move_to_trash(self.ws.root, "demo")
        self.assertNotEqual(a, b)
        self.assertEqual(len(self.ws.trash_list()), 2)

    def test_zip(self):
        p = self.ws.pdir("demo")
        if os.name == "nt":
            self.skipTest("symlinks need privileges on Windows")
        (p / "link").symlink_to(p / "clips" / "a.mp4")
        z = self.ws.export_project("demo")
        names = zipfile.ZipFile(z).namelist()
        z.unlink()
        self.assertIn("demo/clips/a.mp4", names)
        self.assertIn("demo/Story.md", names)
        self.assertNotIn("demo/clips/_discarded/old.mp4", names)
        self.assertNotIn("demo/link", names)
        z = self.ws.export_project("demo", True)
        self.assertIn("demo/clips/_discarded/old.mp4", zipfile.ZipFile(z).namelist())
        z.unlink()


@unittest.skipUnless(HAVE_API, "needs the venv with fastapi + httpx")
class TestRoutes(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.c = TestClient(create_app(self.root, token="tok", static_dir="/nonexistent"))
        self.call("post", "/api/projects", json={"name": "demo"})

    def call(self, m, url, **kw):
        return self.c.request(m.upper(), url, headers=H, **kw)

    def test_auth_required_everywhere(self):
        for m, u in (("get", "/api/projects/demo/edit"), ("put", "/api/projects/demo/edit"), ("post", "/api/projects/demo/edit/export"),
                     ("get", "/api/projects/demo/export-project"), ("delete", "/api/projects/demo"), ("get", "/api/trash"),
                     ("post", "/api/projects/demo/audio?filename=a.mp3")):
            self.assertEqual(getattr(self.c, m)(u).status_code, 401, u)

    def test_edit_roundtrip_and_errors(self):
        self.assertEqual(self.call("put", "/api/projects/demo/edit", json={"aspect": "7:7"}).status_code, 400)
        r = self.call("put", "/api/projects/demo/edit", json={"tracks": {"video": [vid("a")]}})
        self.assertEqual(r.status_code, 200)
        g = self.call("get", "/api/projects/demo/edit").json()
        self.assertTrue(g["saved"])
        self.assertEqual(g["missing"], ["a"])
        self.assertEqual(self.call("get", "/api/projects/nope/edit").status_code, 400)

    def test_nle_caption_and_bundle_routes(self):
        import io
        for u in ("export-fcpxml", "export-edl", "export-subtitles", "export-bundle"):
            self.assertEqual(self.c.get(f"/api/projects/demo/edit/{u}").status_code, 401, u)      # not public
        # nothing saved yet: the timeline exports say so, the captions say there are no cues
        for u in ("export-fcpxml", "export-edl"):
            self.assertEqual(self.call("get", f"/api/projects/demo/edit/{u}").status_code, 400, u)
        r = self.call("get", "/api/projects/demo/edit/export-subtitles")
        self.assertEqual(r.status_code, 400)
        self.assertIn("no subtitle cues", r.json()["detail"])
        self.assertEqual(self.call("get", "/api/projects/demo/edit/export-subtitles?format=xml").status_code, 400)
        self.assertEqual(self.call("get", "/api/projects/nope/edit/export-edl").status_code, 400)
        # with clips and cues every format downloads with its own media type
        self.call("put", "/api/projects/demo/edit", json={"tracks": {
            "video": [vid("a"), vid("b", "clips/b.mp4", tr="crossfade")],
            "subtitles": {"cues": [{"id": "c1", "start": 0, "end": 2, "text": "Hi"}]}}})
        x = self.call("get", "/api/projects/demo/edit/export-fcpxml")
        self.assertEqual(x.status_code, 200)
        self.assertTrue(x.headers["content-type"].startswith("application/xml"))
        self.assertIn('filename="demo.fcpxml"', x.headers["content-disposition"])
        self.assertIn("<fcpxml version=", x.text)
        e = self.call("get", "/api/projects/demo/edit/export-edl")
        self.assertTrue(e.headers["content-type"].startswith("text/plain"))
        self.assertIn("FCM: NON-DROP FRAME", e.text)
        s = self.call("get", "/api/projects/demo/edit/export-subtitles?format=srt")
        self.assertTrue(s.headers["content-type"].startswith("application/x-subrip"))
        self.assertEqual(s.text, editor.export_srt([{"start": 0, "end": 2, "text": "Hi"}]))
        v = self.call("get", "/api/projects/demo/edit/export-subtitles?format=vtt")
        self.assertTrue(v.text.startswith("WEBVTT"))
        b = self.call("get", "/api/projects/demo/edit/export-bundle")
        self.assertEqual(b.status_code, 200)
        self.assertTrue(b.headers["content-type"].startswith("application/zip"))
        self.assertIn("demo-edit-bundle.zip", b.headers["content-disposition"])
        names = zipfile.ZipFile(io.BytesIO(b.content)).namelist()
        for want in ("captions.srt", "captions.vtt", "timeline.fcpxml", "timeline.edl", "timeline_summary.json"):
            self.assertIn(want, names)

    def test_elements_routes(self):
        r = self.call("post", "/api/projects/demo/elements?filename=sticker.png", content=b"\x89PNG\r\n\x1a\nfake")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"src": "elements/sticker.png", "name": "sticker"})
        lst = self.call("get", "/api/projects/demo/elements").json()["elements"]
        self.assertEqual(len(lst), 1)
        self.assertEqual(lst[0]["src"], "elements/sticker.png")
        f = self.call("get", "/files/demo/elements/sticker.png")
        self.assertEqual(f.status_code, 200)
        self.assertEqual(f.content, b"\x89PNG\r\n\x1a\nfake")

    def test_fonts_public_and_whitelisted(self):
        self.assertTrue(self.c.get("/api/fonts").json()["fonts"])
        self.assertEqual(self.c.get("/api/fonts/Poppins-Bold.ttf").status_code, 200)
        self.assertEqual(self.c.get("/api/fonts/..%2Fsecret.txt").status_code, 404)
        self.assertEqual(self.c.get("/api/fonts/OFL.txt").status_code, 404)

    def test_delete_flow_and_zip_download(self):
        z = self.call("get", "/api/projects/demo/export-project")
        self.assertEqual(z.status_code, 200)
        self.assertIn("demo.zip", z.headers["content-disposition"])
        self.assertEqual(self.call("delete", "/api/projects/demo", json={"confirm": "x"}).status_code, 400)
        self.assertEqual(self.call("delete", "/api/projects/demo").status_code, 400)
        tid = self.call("delete", "/api/projects/demo", json={"confirm": "demo"}).json()["trash"]
        self.assertEqual(self.call("get", "/api/projects").json()["projects"], [])
        self.assertEqual(self.call("get", "/api/trash").json()["items"][0]["id"], tid)
        self.assertEqual(self.call("post", f"/api/trash/{tid}/restore").json(), {"name": "demo"})
        self.assertEqual(len(self.call("get", "/api/projects").json()["projects"]), 1)

    @unittest.skipUnless(FF and PILOK, "needs ffmpeg + Pillow")
    def test_export_job(self):
        p = Path(self.root) / "projects" / "demo"
        (p / "clips").mkdir(exist_ok=True)
        make_clip(p / "clips" / "a.mp4", 1.5)
        self.call("put", "/api/projects/demo/edit", json={"tracks": {"video": [vid("a", b=1.5)]}})
        j = self.call("post", "/api/projects/demo/edit/export").json()["job"]
        for _ in range(200):
            r = self.call("get", f"/api/jobs/{j}").json()
            if r["status"] != "running":
                break
            time.sleep(0.1)
        self.assertEqual(r["status"], "done", r)
        f = self.call("get", f"/files/demo/{r['result']['file']}")
        self.assertEqual(f.status_code, 200)
        self.assertGreater(len(f.content), 1000)


if __name__ == "__main__":
    unittest.main()
