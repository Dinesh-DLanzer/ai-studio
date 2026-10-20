import json
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from aistudio import editor


def sample_edit():
    return editor.clean({"fps": 25, "tracks": {
        "video": [
            {"id": "v1", "src": "clips/a.mp4", "in": 0, "out": 4, "volume": 1,
             "transition": {"type": "cut", "dur": 0.5}},
            {"id": "v2", "src": "clips/b.mp4", "in": 0, "out": 4, "volume": 1,
             "transition": {"type": "crossfade", "dur": 1}},
        ],
        "audio": [{"id": "m1", "src": "audio/music.mp3", "start": 1, "in": 0, "out": 5,
                   "volume": 0.5, "fadeIn": 0, "fadeOut": 0, "name": "Music"}],
        "text": [{"id": "t1", "text": "Hello", "start": 2, "end": 3}],
        "subtitles": {"cues": [{"id": "c1", "start": 3, "end": 4, "text": "Caption"}],
                      "style": "classic"},
    }})


def file_map(edit, root="/tmp/demo"):
    return {item["src"]: Path(root) / item["src"]
            for key in ("video", "audio", "elements")
            for item in edit["tracks"].get(key, [])}


class TestInterchangeExports(unittest.TestCase):
    def setUp(self):
        self.edit = sample_edit()
        self.files = file_map(self.edit)

    def test_otio_structure_and_frame_durations(self):
        result = json.loads(editor.export_otio(self.edit, self.files, {}))
        self.assertEqual(result["OTIO_SCHEMA"], "Timeline.1")
        tracks = result["tracks"]["children"]
        self.assertEqual([track["kind"] for track in tracks], ["Video", "Audio"])
        video = tracks[0]
        clips = [item for item in video["children"] if item["OTIO_SCHEMA"].startswith("Clip.")]
        self.assertEqual([clip["name"] for clip in clips], ["a.mp4", "b.mp4"])
        self.assertEqual([clip["media_reference"]["OTIO_SCHEMA"] for clip in clips],
                         ["ExternalReference.1", "ExternalReference.1"])
        self.assertEqual(clips[0]["media_reference"]["target_url"], Path("/tmp/demo/clips/a.mp4").resolve().as_uri())
        self.assertEqual(clips[0]["source_range"]["duration"]["value"], 100)
        self.assertEqual(clips[0]["source_range"]["duration"]["rate"], 25)
        self.assertTrue(any(item["OTIO_SCHEMA"] == "Transition.1" and
                            item["transition_type"] == "SMPTE_Dissolve" for item in video["children"]))
        self.assertTrue(any(item["OTIO_SCHEMA"] == "Gap.1" for item in tracks[1]["children"]))
        markers = video["markers"]
        self.assertEqual({m["name"] for m in markers}, {"Hello", "Caption"})

    def test_xmeml_structure_and_dissolve(self):
        root = ET.fromstring(editor.export_xmeml(self.edit, self.files, {}))
        self.assertEqual((root.tag, root.get("version")), ("xmeml", "4"))
        sequence = root.find("./sequence")
        self.assertEqual(sequence.findtext("./rate/timebase"), "25")
        video_tracks = sequence.findall("./media/video/track")
        audio_tracks = sequence.findall("./media/audio/track")
        self.assertEqual(len(video_tracks), 1)
        self.assertEqual(len(audio_tracks), 1)
        clips = video_tracks[0].findall("clipitem")
        self.assertEqual([clip.findtext("name") for clip in clips], ["a.mp4", "b.mp4"])
        self.assertEqual([(clip.findtext("in"), clip.findtext("out"),
                           clip.findtext("start"), clip.findtext("end")) for clip in clips],
                         [("0", "100", "0", "100"), ("0", "100", "75", "175")])
        self.assertTrue(any(child.tag == "transitionitem" for child in video_tracks[0]))
        self.assertEqual(audio_tracks[0].find("clipitem/file/name").text, "music.mp3")

    def test_bundle_includes_otio_and_xmeml(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            pdir = Path(tmp) / "demo"
            pdir.mkdir()
            # Missing media is intentionally allowed for timeline-only bundle exports.
            bundle = editor.export_bundle(pdir, self.edit, self.files)
            try:
                with zipfile.ZipFile(bundle) as archive:
                    self.assertIn("timeline.otio", archive.namelist())
                    self.assertIn("timeline.xml", archive.namelist())
                    self.assertEqual(json.loads(archive.read("timeline.otio"))["OTIO_SCHEMA"], "Timeline.1")
                    self.assertEqual(ET.fromstring(archive.read("timeline.xml")).tag, "xmeml")
            finally:
                Path(bundle).unlink(missing_ok=True)


try:
    import opentimelineio as _otio  # noqa: F401
    HAVE_OTIO = True
except ImportError:
    HAVE_OTIO = False


@unittest.skipUnless(HAVE_OTIO, "opentimelineio is not installed")
class TestOtioAdapter(unittest.TestCase):
    def test_opentimelineio_reads_export(self):
        import tempfile
        edit = sample_edit()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timeline.otio"
            path.write_text(editor.export_otio(edit, file_map(edit, tmp), {}))
            timeline = _otio.adapters.read_from_file(str(path))
            self.assertEqual(timeline.name, "demo")
