"""Audio task pipeline regressions. All provider calls use the deterministic fake adapter."""
import tests._hermetic as HERM  # noqa: F401
import tempfile
import unittest
from unittest.mock import patch
import json
import shutil
import subprocess
from pathlib import Path

from aistudio.providers import config
from aistudio.providers.adapters.fake import FakeAdapter
from aistudio.service import Workspace


class TestAudioRoleWiring(unittest.TestCase):
    def test_audio_roles_are_configurable(self):
        roles = config.default_roles()["roles"]
        for role in ("tts", "music", "sfx", "lipsync", "transcribe"):
            self.assertIn(role, roles)
            self.assertEqual(config.validate_chain(role, [], config.default_providers()), [])

    def test_fake_adapter_implements_all_audio_tasks(self):
        for task in ("tts", "music", "sfx", "lipsync", "transcribe"):
            self.assertIn(task, FakeAdapter.task_methods)


class TestAudioPipeline(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.ws = Workspace(tempfile.mkdtemp())
        self.ws.create_project("audio")
        self.p = self.ws.pdir("audio")
        self.ws.estimate("audio", 0.5)
        self.ws.approve_budget("audio")
        budget = self.ws._read(self.p, "budget.json", {})
        budget["stop_loss"] = 5.0
        (self.p / "budget.json").write_text(json.dumps(budget), encoding="utf-8")

    def test_tts_proposal_is_priceable_and_needs_human_approval(self):
        proposal = self.ws.propose("audio", "tts", "s01", options={"text": "வணக்கம்", "voice_id": "fake-voice"})
        self.assertEqual(proposal["price"], 0.0)
        with self.assertRaises(Exception):
            self.ws.execute("audio", proposal["id"])
        self.ws.approve_human("audio", proposal["id"])
        result = self.ws.execute("audio", proposal["id"])
        self.assertTrue((self.p / result["file"]).is_file())

    def test_cloned_voice_requires_voice_consent_before_proposal(self):
        from aistudio import consent
        options = {"text": "Hello", "voice_id": "clone-1", "cloned": True, "voice_subject": "Asha Rao"}
        with self.assertRaises(Exception):
            self.ws.propose("audio", "tts", "s01", options=options)
        consent.record(self.p, "Asha Rao", "I consent to voice synthesis", "voice")
        proposal = self.ws.propose("audio", "tts", "s01", options=options)
        self.assertTrue(proposal["id"])
        self.ws.approve_human("audio", proposal["id"])
        (self.p / "consent.json").write_text("[]", encoding="utf-8")
        with self.assertRaises(Exception):
            self.ws.execute("audio", proposal["id"])

    def test_audio_task_fails_closed_without_adapter_method(self):
        with patch.object(FakeAdapter, "task_methods", frozenset()):
            with self.assertRaises(Exception):
                self.ws.propose("audio", "tts", "s01", options={"text": "hello", "voice_id": "fake-voice"})

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe not installed")
    def test_lipsync_rechecks_approval_and_source_sha(self):
        audio = self.p / "audio" / "voice.wav"
        video = self.p / "clips" / "source.mp4"
        audio.parent.mkdir(parents=True, exist_ok=True)
        video.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-y", str(audio)], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1", "-y", str(video)], check=True)
        HERM.register_test_media(self.p, "clips/source.mp4", "audio/voice.wav")
        proposal = self.ws.propose("audio", "lipsync", "source", options={"video": "clips/source.mp4", "audio": "audio/voice.wav"})
        with self.assertRaises(Exception):
            self.ws.execute("audio", proposal["id"])
        self.ws.approve_human("audio", proposal["id"])
        video.write_bytes(b"changed bytes")
        with self.assertRaises(Exception):
            self.ws.execute("audio", proposal["id"])

    def test_voiceover_plan_freezes_one_item_per_voice_line_and_sums_quotes(self):
        from tests.test_story_convert import MD
        self.ws.put_text("audio", "Story.md", MD)
        self.ws.convert_story("audio")
        batch = self.ws.voiceover_plan("audio", {"voice_id": "fake-voice"})
        self.assertEqual(batch["status"], "awaiting_approval")
        self.assertEqual(len(batch["items"]), 2)
        self.assertEqual(batch["total"], round(sum(i["price"] for i in batch["items"]), 6))
        self.assertTrue(all(i["kind"] == "tts" and i["options"]["language"] == (self.ws.brief_get("audio").get("language") or "") for i in batch["items"]))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe not installed")
    def test_all_kinds_propose_approve_execute_and_log_exact_quote(self):
        audio = self.p / "audio" / "source.wav"
        video = self.p / "clips" / "source.mp4"
        audio.parent.mkdir(parents=True, exist_ok=True)
        video.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-y", str(audio)], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=2", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-y", str(video)], check=True)
        HERM.register_test_media(self.p, "clips/source.mp4", "audio/source.wav")
        cards = {"kind": "audio", "per_1k_chars": 0.1, "per_minute": 0.06, "per_run": 0.25, "per_second": 0.02}
        (self.ws.settings_dir / "models.json").write_text(json.dumps({"prices": {"fake|fake/audio": cards}}), encoding="utf-8")
        requests = [
            ("tts", "v1", {"text": "வணக்கம்", "voice_id": "fake-voice"}, 0.0007),
            ("music", "bed", {"prompt": "warm strings", "seconds": 3}, 0.06),
            ("sfx", "hit", {"prompt": "soft impact", "seconds": 2}, 0.04),
            ("transcribe", "source", {"source": "audio/source.wav"}, 0.002),
            ("lipsync", "source", {"video": "clips/source.mp4", "audio": "audio/source.wav"}, 0.002),
        ]
        for kind, target, opts, quote in requests:
            proposal = self.ws.propose("audio", kind, target, options=opts)
            self.assertAlmostEqual(proposal["price"], quote, places=6, msg=kind)
            self.ws.approve_human("audio", proposal["id"])
            result = self.ws.execute("audio", proposal["id"])
            self.assertTrue((self.p / result["file"]).is_file(), kind)
            row = [r for r in __import__("aistudio.costlog", fromlist=["read_log"]).read_log(self.p) if r["shot"] == target][-1]
            self.assertAlmostEqual(float(row["cost"]), quote, places=6, msg=kind)
            self.assertEqual(row["result"], "completed")
