"""whisper.cpp (local transcription) adapter: the exact argv it runs, the JSON it reads, the failure paths.

The two local programs (ffmpeg and the whisper.cpp binary) are mocked at the subprocess level, so the test
never needs whisper.cpp, ffmpeg or a model file installed.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aistudio.providers.adapters.whisper_cpp import WhisperCppAdapter, parse_transcript
from aistudio.providers.base import AuthError, Rejected, Retryable

FIXTURE = Path(__file__).parent / "fixtures" / "whisper_cpp_output.json"
FIXTURE_DOC = json.loads(FIXTURE.read_text(encoding="utf-8"))

PATCH_RUN = "aistudio.providers.adapters.whisper_cpp.subprocess.run"
PATCH_WHICH = "aistudio.providers.adapters.whisper_cpp.shutil.which"


class TestWhisperCpp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aistudio-test-whisper-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.tools = self.tmp / "tools"
        self.tools.mkdir()
        self.whisper = self.tools / "whisper-cli"          # stands in for the whisper.cpp binary
        self.whisper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.model = self.tools / "ggml-base.en.bin"       # stands in for the ggml model file
        self.model.write_bytes(b"GGML")
        self.ffmpeg = "/opt/tools/ffmpeg"                 # ffmpeg is found on PATH (mocked)
        self.audio = self.tmp / "voice.mp3"
        self.audio.write_bytes(b"ID3fakeaudio")
        self.work = self.tmp / "project"
        self.work.mkdir()

    # ---------------------------------------------------------------- helpers
    def which(self, name):
        return {"ffmpeg": self.ffmpeg, "whisper-cli": str(self.whisper)}.get(name)

    def fake_run(self, calls, ffmpeg_rc=0, whisper_rc=0, stderr="", write_json=True):
        """Stand-in for subprocess.run: ffmpeg writes the wav, whisper-cli writes the JSON next to the -of prefix."""
        def run(cmd, **kwargs):
            cmd = list(cmd)
            calls.append({"cmd": cmd, "kwargs": kwargs})
            if cmd[0] == self.ffmpeg:
                if ffmpeg_rc == 0:
                    Path(cmd[-1]).write_bytes(b"RIFFfakewav")
            else:
                if whisper_rc == 0 and write_json and "-of" in cmd:
                    prefix = cmd[cmd.index("-of") + 1]
                    Path(prefix + ".json").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
            return subprocess.CompletedProcess(cmd, whisper_rc if cmd[0] != self.ffmpeg else ffmpeg_rc, "", stderr)
        return run

    def adapter(self, secret=None):
        calls = []
        conn = {"id": "w", "type": "whisper_cpp",
                "secret": secret if secret is not None else {"binary": str(self.whisper), "model_path": str(self.model)}}
        return WhisperCppAdapter(conn), calls

    def run_with(self, calls, **kw):
        return mock.patch(PATCH_RUN, self.fake_run(calls, **kw)), mock.patch(PATCH_WHICH, self.which)

    # ---------------------------------------------------------------- tests
    def test_transcribe_runs_ffmpeg_then_whisper_with_exact_argv(self):
        a, calls = self.adapter()
        run_patch, which_patch = self.run_with(calls)
        with run_patch, which_patch:
            out = a.transcribe("whisper-cpp", str(self.audio),
                               {"workdir": str(self.work), "language": "en", "threads": 4})

        self.assertEqual(len(calls), 2)
        ff, wh = calls[0]["cmd"], calls[1]["cmd"]
        self.assertEqual(ff[0], self.ffmpeg)
        self.assertEqual(ff[1:6], ["-y", "-nostdin", "-hide_banner", "-loglevel", "error"])
        self.assertEqual(ff[6], "-i")
        self.assertEqual(ff[7], str(self.audio))
        self.assertEqual(ff[8:14], ["-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le"])
        wav = ff[14]
        self.assertTrue(wav.startswith(str(self.work) + os.sep), wav)          # the work happens inside the project
        self.assertTrue(wav.endswith("audio16k.wav"), wav)

        self.assertEqual(wh[0], str(self.whisper))
        self.assertEqual(wh[1:3], ["-m", str(self.model)])
        self.assertEqual(wh[3:5], ["-f", wav])
        self.assertEqual(wh[5:7], ["-l", "en"])
        self.assertEqual(wh[7:9], ["-t", "4"])
        self.assertEqual(wh[9:11], ["-ojf", "-of"])
        self.assertTrue(wh[11].startswith(str(self.work) + os.sep), wh[11])
        self.assertEqual(wh[12:], ["-np"])

        for c in calls:                                    # never a shell, never an inherited stdin
            self.assertNotIn("shell", c["kwargs"])
            self.assertTrue(c["kwargs"]["cwd"].startswith(str(self.work) + os.sep), c["kwargs"]["cwd"])
            self.assertTrue(c["kwargs"]["timeout"] > 0)

        self.assertEqual(out["language"], "en")
        self.assertEqual(out["text"], "And so my fellow Americans, ask not what your country can do for you, ask what you can do for your country.")
        self.assertEqual(out["words"][0], {"text": "And", "start": 0.0, "end": 0.32})
        self.assertEqual(out["words"][5], {"text": ",", "start": 1.59, "end": 2.85})
        self.assertEqual(len(out["words"]), 16)

    def test_temp_files_are_removed_afterwards(self):
        a, calls = self.adapter()
        run_patch, which_patch = self.run_with(calls)
        with run_patch, which_patch:
            a.transcribe("whisper-cpp", str(self.audio), {"workdir": str(self.work)})
        self.assertEqual([p.name for p in self.work.iterdir()], [])

    def test_parse_transcript_from_the_fixture(self):
        out = parse_transcript(FIXTURE_DOC)
        self.assertEqual(out["language"], "en")
        self.assertEqual(out["words"][0], {"text": "And", "start": 0.0, "end": 0.32})
        self.assertEqual(out["words"][-1], {"text": ",", "start": 7.01, "end": 8.17})
        self.assertTrue(out["text"].startswith("And so my fellow Americans,"))

    def test_parse_transcript_without_tokens_falls_back_to_the_segment_text(self):
        doc = {"result": {"language": "ta"}, "transcription": [{"text": " வணக்கம்", "offsets": {"from": 0, "to": 500}}]}
        out = parse_transcript(doc)
        self.assertEqual(out, {"text": "வணக்கம்", "words": [], "language": "ta"})

    def test_missing_binary_is_reported_and_never_raises(self):
        a, calls = self.adapter(secret={"model_path": str(self.model)})
        with mock.patch(PATCH_WHICH, lambda n: None):
            res = a.test()
        self.assertFalse(res["ok"])
        self.assertIn("whisper", res["message"].lower())
        self.assertEqual(calls, [])

    def test_transcribe_without_a_binary_raises(self):
        a, calls = self.adapter(secret={"model_path": str(self.model)})
        with mock.patch(PATCH_WHICH, lambda n: None):
            with self.assertRaises(AuthError):
                a.transcribe("whisper-cpp", str(self.audio), {"workdir": str(self.work)})

    def test_missing_model_is_reported(self):
        a, _ = self.adapter(secret={"binary": str(self.whisper), "model_path": "/nope/ggml.bin"})
        with mock.patch(PATCH_WHICH, self.which):
            self.assertFalse(a.test()["ok"])
            with self.assertRaises(AuthError):
                a.transcribe("whisper-cpp", str(self.audio), {"workdir": str(self.work)})

    def test_test_runs_help_and_reports_ok(self):
        a, calls = self.adapter()
        run_patch, which_patch = self.run_with(calls)
        with run_patch, which_patch:
            res = a.test()
        self.assertTrue(res["ok"], res)
        self.assertEqual(calls[0]["cmd"], [str(self.whisper), "--help"])

    def test_binary_discovery_prefers_whisper_cli(self):
        a, _ = self.adapter(secret={"model_path": str(self.model)})
        with mock.patch(PATCH_WHICH, lambda n: {"whisper-cli": str(self.whisper)}.get(n)):
            self.assertEqual(a.binary_path(), str(self.whisper))
        with mock.patch(PATCH_WHICH, lambda n: {"whisper-cpp": "/old/whisper-cpp"}.get(n)):
            self.assertEqual(a.binary_path(), "/old/whisper-cpp")
        with mock.patch(PATCH_WHICH, lambda n: None):
            self.assertIsNone(a.binary_path())

    def test_ffmpeg_failure_is_rejected(self):
        a, calls = self.adapter()
        run_patch, which_patch = self.run_with(calls, ffmpeg_rc=1, stderr="Invalid data found")
        with run_patch, which_patch:
            with self.assertRaises(Rejected) as e:
                a.transcribe("whisper-cpp", str(self.audio), {"workdir": str(self.work)})
        self.assertIn("ffmpeg", str(e.exception).lower())

    def test_whisper_failure_is_rejected(self):
        a, calls = self.adapter()
        run_patch, which_patch = self.run_with(calls, whisper_rc=1, stderr="failed to load model")
        with run_patch, which_patch:
            with self.assertRaises(Rejected) as e:
                a.transcribe("whisper-cpp", str(self.audio), {"workdir": str(self.work)})
        self.assertIn("failed to load model", str(e.exception))

    def test_timeout_is_retryable(self):
        a, calls = self.adapter()

        def boom(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 5)

        with mock.patch(PATCH_RUN, boom), mock.patch(PATCH_WHICH, self.which):
            with self.assertRaises(Retryable):
                a.transcribe("whisper-cpp", str(self.audio), {"workdir": str(self.work)})

    def test_missing_json_output_is_retryable(self):
        a, calls = self.adapter()
        run_patch, which_patch = self.run_with(calls, write_json=False)
        with run_patch, which_patch:
            with self.assertRaises(Retryable):
                a.transcribe("whisper-cpp", str(self.audio), {"workdir": str(self.work)})


if __name__ == "__main__":
    unittest.main()
