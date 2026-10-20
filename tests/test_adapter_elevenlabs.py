"""Tests for ElevenLabs adapter using FakeTransport."""
import base64
import unittest
from aistudio.providers.adapters.elevenlabs import ElevenLabsAdapter
from aistudio.providers.base import Retryable, AuthError, Rejected, NotFound
from tests._adapter_helpers import FakeTransport


CONN = {"id": "el", "type": "elevenlabs", "secret": {"api_key": "xi-test-key-12345"}}
AUDIO_BYTES = b"FAKE_MP3_DATA_" + b"x" * 100
B64_AUDIO = base64.b64encode(AUDIO_BYTES).decode()


def make_adapter(*answers):
    t = FakeTransport(*answers)
    return ElevenLabsAdapter(CONN, transport=t), t


class TestElevenLabsAdapter(unittest.TestCase):
    # -------------------------- list_models --------------------------
    def test_list_models(self):
        models_resp = [
            {"model_id": "eleven_multilingual_v2", "name": "Eleven Multilingual v2",
             "can_do_text_to_speech": True, "can_do_voice_conversion": False},
            {"model_id": "eleven_text_to_sound_v2", "name": "Sound Effects v2",
             "can_do_text_to_speech": False, "can_do_voice_conversion": False},
            {"model_id": "music_v1", "name": "Music v1",
             "can_do_text_to_speech": False, "can_do_voice_conversion": False},
            {"model_id": "scribe_v2", "name": "Scribe v2",
             "can_do_text_to_speech": False, "can_do_voice_conversion": False},
        ]
        a, t = make_adapter(models_resp)
        got = a.list_models()
        self.assertEqual(t.last["url"], "https://api.elevenlabs.io/v1/models")
        self.assertEqual(t.last["headers"]["xi-api-key"], "xi-test-key-12345")
        self.assertEqual(len(got), 4)
        self.assertEqual(got[0]["capability"], "tts")
        self.assertEqual(got[1]["capability"], "sfx")
        self.assertEqual(got[2]["capability"], "music")
        self.assertEqual(got[3]["capability"], "transcribe")

    # -------------------------- test() --------------------------
    def test_test_ok_user_endpoint(self):
        a, t = make_adapter({"subscription": {"tier": "creator"}})
        res = a.test()
        self.assertTrue(res["ok"])
        self.assertEqual(t.last["url"], "https://api.elevenlabs.io/v1/user")

    def test_test_ok_fallback_voices(self):
        a, t = make_adapter(Exception("no user"), {"voices": [], "has_more": False})
        res = a.test()
        self.assertTrue(res["ok"])
        self.assertEqual(t.last["url"], "https://api.elevenlabs.io/v2/voices?page_size=1")

    def test_test_fail(self):
        a, t = make_adapter(Exception("no user"), AuthError("bad key"))
        res = a.test()
        self.assertFalse(res["ok"])
        self.assertIn("bad key", res["message"].lower())

    # -------------------------- tts --------------------------
    def test_tts_happy(self):
        a, t = make_adapter(AUDIO_BYTES)
        out = a.tts("eleven_multilingual_v2", "Hello world", "voice-123")
        self.assertEqual(t.last["method"], "POST")
        self.assertIn("/v1/text-to-speech/voice-123", t.last["url"])
        self.assertEqual(t.last["body"]["text"], "Hello world")
        self.assertEqual(t.last["body"]["model_id"], "eleven_multilingual_v2")
        self.assertEqual(out["bytes"], AUDIO_BYTES)
        self.assertEqual(out["mime"], "audio/mpeg")
        self.assertEqual(out["model"], "eleven_multilingual_v2")

    def test_tts_with_voice_settings(self):
        a, t = make_adapter(AUDIO_BYTES)
        a.tts("m", "text", "v", {"voice_settings": {"stability": 0.3, "similarity_boost": 0.8}})
        self.assertEqual(t.last["body"]["voice_settings"], {"stability": 0.3, "similarity_boost": 0.8})

    def test_tts_auth_error(self):
        a, t = make_adapter(AuthError("invalid api key"))
        with self.assertRaises(AuthError):
            a.tts("m", "text", "v")

    def test_tts_rate_limit(self):
        a, t = make_adapter(Retryable("rate limited"))
        with self.assertRaises(Retryable):
            a.tts("m", "text", "v")

    def test_tts_rejected(self):
        a, t = make_adapter(Rejected("voice not found"))
        with self.assertRaises(Rejected):
            a.tts("m", "text", "v")

    def test_tts_secret_not_in_error(self):
        # The scrub function should remove the secret from error messages
        from aistudio.providers.base import scrub
        secret = {"api_key": "xi-test-key-12345"}
        msg = scrub("Error: xi-test-key-12345 leaked", secret)
        self.assertNotIn("xi-test-key-12345", msg)
        self.assertIn("***", msg)

    # -------------------------- sfx --------------------------
    def test_sfx_happy(self):
        a, t = make_adapter(AUDIO_BYTES)
        out = a.sfx("eleven_text_to_sound_v2", "explosion", 3.0)
        self.assertEqual(t.last["method"], "POST")
        self.assertIn("/v1/sound-generation", t.last["url"])
        self.assertEqual(t.last["body"]["text"], "explosion")
        self.assertEqual(t.last["body"]["model_id"], "eleven_text_to_sound_v2")
        self.assertEqual(t.last["body"]["duration_seconds"], 3.0)
        self.assertEqual(out["bytes"], AUDIO_BYTES)

    def test_sfx_with_loop_and_prompt_influence(self):
        a, t = make_adapter(AUDIO_BYTES)
        a.sfx("m", "hum", 5.0, {"loop": True, "prompt_influence": 0.5})
        self.assertTrue(t.last["body"]["loop"])
        self.assertEqual(t.last["body"]["prompt_influence"], 0.5)

    def test_sfx_auth_error(self):
        a, t = make_adapter(AuthError("bad key"))
        with self.assertRaises(AuthError):
            a.sfx("m", "p", 1)

    def test_sfx_rate_limit(self):
        a, t = make_adapter(Retryable("429"))
        with self.assertRaises(Retryable):
            a.sfx("m", "p", 1)

    def test_sfx_rejected(self):
        a, t = make_adapter(Rejected("bad prompt"))
        with self.assertRaises(Rejected):
            a.sfx("m", "p", 1)

    # -------------------------- music --------------------------
    def test_music_happy(self):
        a, t = make_adapter(AUDIO_BYTES)
        out = a.music("music_v1", "upbeat pop", 30)
        self.assertEqual(t.last["method"], "POST")
        self.assertIn("/v1/music", t.last["url"])
        self.assertEqual(t.last["body"]["prompt"], "upbeat pop")
        self.assertEqual(t.last["body"]["model_id"], "music_v1")
        self.assertEqual(t.last["body"]["music_length_ms"], 30000)
        self.assertEqual(out["bytes"], AUDIO_BYTES)

    def test_music_with_optional_fields(self):
        a, t = make_adapter(AUDIO_BYTES)
        a.music("music_v2", "jazz", 60, {"force_instrumental": True, "seed": 42})
        self.assertTrue(t.last["body"]["force_instrumental"])
        self.assertEqual(t.last["body"]["seed"], 42)

    def test_music_auth_error(self):
        a, t = make_adapter(AuthError("bad key"))
        with self.assertRaises(AuthError):
            a.music("m", "p", 10)

    def test_music_rate_limit(self):
        a, t = make_adapter(Retryable("429"))
        with self.assertRaises(Retryable):
            a.music("m", "p", 10)

    def test_music_rejected(self):
        a, t = make_adapter(Rejected("model not available"))
        with self.assertRaises(Rejected):
            a.music("m", "p", 10)

    # -------------------------- transcribe --------------------------
    def test_transcribe_happy(self):
        a, t = make_adapter({
            "text": "Hello world",
            "words": [
                {"text": "Hello", "start": 0.0, "end": 0.5, "speaker_id": "speaker_1"},
                {"text": "world", "start": 0.5, "end": 1.0, "speaker_id": "speaker_1"},
            ]
        })
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mktemp(suffix=".mp3"))
        tmp.write_bytes(b"fake audio")
        try:
            out = a.transcribe("scribe_v2", str(tmp))
        finally:
            tmp.unlink(missing_ok=True)
        self.assertEqual(t.last["method"], "POST")
        self.assertIn("/v1/speech-to-text", t.last["url"])
        self.assertEqual(out["text"], "Hello world")
        self.assertEqual(len(out["words"]), 2)
        self.assertEqual(out["words"][0]["text"], "Hello")
        self.assertEqual(out["words"][0]["start"], 0.0)
        self.assertEqual(out["words"][0]["end"], 0.5)
        self.assertEqual(out["words"][0]["speaker_id"], "speaker_1")

    def test_transcribe_auth_error(self):
        a, t = make_adapter(AuthError("bad key"))
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mktemp(suffix=".mp3"))
        tmp.write_bytes(b"fake audio")
        try:
            with self.assertRaises(AuthError):
                a.transcribe("scribe_v2", str(tmp))
        finally:
            tmp.unlink(missing_ok=True)

    def test_transcribe_rate_limit(self):
        a, t = make_adapter(Retryable("429"))
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mktemp(suffix=".mp3"))
        tmp.write_bytes(b"fake audio")
        try:
            with self.assertRaises(Retryable):
                a.transcribe("scribe_v2", str(tmp))
        finally:
            tmp.unlink(missing_ok=True)

    def test_transcribe_rejected(self):
        a, t = make_adapter(Rejected("file too large"))
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mktemp(suffix=".mp3"))
        tmp.write_bytes(b"fake audio")
        try:
            with self.assertRaises(Rejected):
                a.transcribe("scribe_v2", str(tmp))
        finally:
            tmp.unlink(missing_ok=True)

    # -------------------------- list_voices --------------------------
    def test_list_voices(self):
        voices_resp = {"voices": [
            {"voice_id": "v1", "name": "Rachel", "category": "premade"},
            {"voice_id": "v2", "name": "Custom Voice", "category": "cloned"},
        ], "has_more": False}
        a, t = make_adapter(voices_resp)
        got = a.list_voices()
        self.assertEqual(t.last["url"], "https://api.elevenlabs.io/v2/voices")
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0]["voice_id"], "v1")
        self.assertEqual(got[1]["category"], "cloned")


if __name__ == "__main__":
    unittest.main()