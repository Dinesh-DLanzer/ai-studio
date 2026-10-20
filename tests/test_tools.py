import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aistudio import tools


class LocalToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        (self.project / "clips").mkdir()
        self.src = self.project / "clips" / "source.mp4"
        self.src.touch()

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, name, params, suffix=".mp4"):
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            if argv[-1] != "-":
                Path(argv[-1]).touch()
            return subprocess.CompletedProcess(argv, 0)
        out = tools.run_local(name, self.src, self.project / "clips" / f"result{suffix}", params,
                              self.project, runner=runner)
        return calls[0], out

    def test_registry_and_filter_probe_are_cached(self):
        with patch.object(tools.shutil, "which", return_value="/usr/bin/ffmpeg"), patch.object(
                tools.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout=" ... vidstabdetect ...\n")) as run:
            tools._filters.cache_clear()
            self.assertIn("stabilize", tools.available())
            self.assertEqual(tools.available(), tools.available())
            self.assertEqual(run.call_count, 1)
            self.assertEqual(tools.TOOLS["reframe_local"]["kind"], "local")

    def test_reframe_blur_pad_argv_and_new_version(self):
        argv, out = self.run_tool("reframe_local", {"aspect": "9:16", "mode": "blur-pad"})
        self.assertEqual(argv, ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(self.src.resolve()),
                                "-filter_complex", "[0:v]split=2[bg][fg];[bg]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,boxblur=20:10[bg];[fg]scale=720:1280:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v]",
                                "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-c:a", "copy", str(out)])
        self.assertEqual(out.name, "result.v1.mp4")
        out.touch()
        _, out2 = self.run_tool("reframe_local", {"aspect": "1:1", "mode": "pad"})
        self.assertEqual(out2.name, "result.v2.mp4")

    def test_upscale_argv(self):
        argv, out = self.run_tool("upscale_local", {"scale": 2})
        self.assertEqual(argv, ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(self.src.resolve()),
                                "-vf", "scale=iw*2:ih*2:flags=lanczos", "-c:v", "libx264", "-c:a", "copy", str(out)])

    def test_interpolate_argv(self):
        argv, out = self.run_tool("interpolate", {"fps": 48, "slowmo": 2})
        self.assertEqual(argv, ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(self.src.resolve()),
                                "-vf", "minterpolate=fps=48,setpts=2*PTS", "-c:v", "libx264", "-c:a", "copy", str(out)])

    def test_speed_and_loop_argv(self):
        argv, out = self.run_tool("speed", {"factor": 2})
        self.assertEqual(argv, ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(self.src.resolve()),
                                "-vf", "setpts=0.5*PTS", "-af", "atempo=2", "-c:v", "libx264", "-c:a", "aac", str(out)])
        argv, out = self.run_tool("loop", {"times": 3})
        self.assertEqual(argv, ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-stream_loop", "2",
                                "-i", str(self.src.resolve()), "-c", "copy", str(out)])

    def test_stabilize_argv(self):
        with patch.object(tools, "_has_filter", return_value=True):
            calls = []
            def runner(argv, **kwargs):
                calls.append(argv)
                return subprocess.CompletedProcess(argv, 0)
            out = tools.run_local("stabilize", self.src, self.project / "clips" / "result.mp4", {}, self.project, runner=runner)
        self.assertEqual(len(calls), 2)
        trf = calls[0][calls[0].index("-vf") + 1].split("result=", 1)[1]
        self.assertEqual(calls[0], ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(self.src.resolve()),
                                    "-vf", f"vidstabdetect=shakiness=5:accuracy=15:result={trf}", "-f", "null", "-"])
        self.assertEqual(calls[1], ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(self.src.resolve()),
                                    "-vf", f"vidstabtransform=input={trf}:smoothing=10", "-c:v", "libx264", "-c:a", "copy", str(out)])

    def test_paths_and_params_are_strict(self):
        with self.assertRaises(ValueError):
            tools.run_local("upscale_local", self.src, self.project.parent / "escape.mp4", {"scale": 2}, self.project)
        for name, params in (("upscale_local", {"scale": 4}), ("speed", {"factor": 0}),
                             ("loop", {"times": True}), ("reframe_local", {"aspect": "4:3", "mode": "crop"}),
                             ("interpolate", {"fps": 48, "slowmo": 3}), ("reframe_local", {"aspect": "9:16", "mode": "crop", "extra": 1})):
            with self.subTest(name=name, params=params), self.assertRaises(ValueError):
                tools.run_local(name, self.src, self.project / "clips" / "result.mp4", params, self.project,
                                runner=lambda *a, **k: self.fail("runner should not be called"))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
class RealFFmpegToolTest(unittest.TestCase):
    def test_blur_pad_reframes_to_vertical(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            src = project / "wide.mp4"
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x180:d=1", "-pix_fmt", "yuv420p", str(src)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            out = tools.run_local("reframe_local", src, project / "vertical.mp4", {"aspect": "9:16", "mode": "blur-pad"}, project)
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "json", str(out)],
                                   check=True, capture_output=True, text=True)
            stream = json.loads(probe.stdout)["streams"][0]
            self.assertAlmostEqual(stream["width"] / stream["height"], 9 / 16, places=2)
