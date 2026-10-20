"""Tests for Sarvam AI adapter using FakeTransport."""
import base64
import unittest
from aistudio.providers.adapters.sarvam import SarvamAdapter
from aistudio.providers.base import Retryable, AuthError, Rejected
from tests._adapter_helpers import FakeTransport


CONN = {"id": "sarvam", "type": "sarvam", "secret": {"api_key": "sarvam-test-key-123456789012"}}
AUDIO_BYTES = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"x" * 100
B64_AUDIO = base64.b64encode(AUDIO_BYTES).decode()


def make_adapter(*answers):
    t = FakeTransport(*answers)
    return SarvamAdapter(CONN, transport=t), t


class TestSarvamAdapter(unittest.TestCase):
    # -------------------------- list_models --------------------------
    def test_list_models(self):
        a, t = make_adapter()
        got = a.list_models()
        self.assertEqual(len(got), 5)
        ids = [m["id"] for m in got]
        self.assertIn("bulbul:v4-flash", ids)
        self.assertIn("bulbul:v3", ids)
        self.assertIn("bulbul:v2", ids)
        self.assertIn("saaras:v4", ids)
        self.assertIn("saaras:v3", ids)

    # -------------------------- test() --------------------------
    def test_test_ok(self):
        a, t = make_adapter({"audios": [B64_AUDIO]})
        res = a.test()
        self.assertTrue(res["ok"])
        self.assertIn("/text-to-speech", t.last["url"])

    def test_test_fail(self):
        a, t = make_adapter(AuthError("invalid api key"))
        res = a.test()
        self.assertFalse(res["ok"])
        self.assertIn("invalid api key", res["message"].lower())

    # -------------------------- tts --------------------------
    def test_tts_happy_v3(self):
        a, t = make_adapter({"audios": [B64_AUDIO], "request_id": "req-123"})
        out = a.tts("bulbul:v3", "Hello world", "shubh", {"language_code": "hi-IN"})
        self.assertEqual(t.last["method"], "POST")
        self.assertIn("/text-to-speech", t.last["url"])
        self.assertEqual(t.last["headers"]["api-subscription-key"], "sarvam-test-key-123456789012")
        self.assertEqual(t.last["body"]["text"], "Hello world")
        self.assertEqual(t.last["body"]["speaker"], "shubh")
        self.assertEqual(t.last["body"]["model"], "bulbul:v3")
        self.assertEqual(t.last["body"]["language_code"], "hi-IN")
        self.assertEqual(out["bytes"], AUDIO_BYTES)
        self.assertEqual(out["mime"], "audio/wav")

    def test_tts_happy_v2_with_pitch_loudness(self):
        a, t = make_adapter({"audios": [B64_AUDIO]})
        out = a.tts("bulbul:v2", "नमस्ते", "anushka", {"pitch": 0.5, "loudness": 1.2, "pace": 1.1})
        self.assertEqual(t.last["body"]["model"], "bulbul:v2")
        self.assertEqual(t.last["body"]["pitch"], 0.5)
        self.assertEqual(t.last["body"]["loudness"], 1.2)
        self.assertEqual(t.last["body"]["pace"], 1.1)

    def test_tts_v3_no_pitch_loudness(self):
        a, t = make_adapter({"audios": [B64_AUDIO]})
        a.tts("bulbul:v3", "text", "shubh", {"pitch": 0.5, "loudness": 1.2})
        # pitch and loudness should NOT be sent for v3
        self.assertNotIn("pitch", t.last["body"])
        self.assertNotIn("loudness", t.last["body"])

    def test_tts_auth_error(self):
        a, t = make_adapter(AuthError("invalid api key"))
        with self.assertRaises(AuthError):
            a.tts("bulbul:v3", "text", "shubh")

    def test_tts_rate_limit(self):
        a, t = make_adapter(Retryable("rate limited"))
        with self.assertRaises(Retryable):
            a.tts("bulbul:v3", "text", "shubh")

    def test_tts_rejected(self):
        a, t = make_adapter(Rejected("invalid speaker"))
        with self.assertRaises(Rejected):
            a.tts("bulbul:v3", "text", "invalid_speaker")

    def test_tts_secret_not_in_error(self):
        from aistudio.providers.base import scrub
        secret = {"api_key": "sarvam-test-key-123456789012"}
        msg = scrub("Error: sarvam-test-key-123456789012 leaked", secret)
        self.assertNotIn("sarvam-test-key-123456789012", msg)
        self.assertIn("***", msg)

    def test_tts_different_codecs(self):
        for codec, mime in [("mp3", "audio/mpeg"), ("flac", "audio/flac"), ("aac", "audio/aac"), ("opus", "audio/opus")]:
            a, t = make_adapter({"audios": [B64_AUDIO]})
            out = a.tts("bulbul:v3", "text", "shubh", {"output_audio_codec": codec})
            self.assertEqual(out["mime"], mime)

    # -------------------------- transcribe --------------------------
    def test_transcribe_happy(self):
        resp = {
            "request_id": "req-123",
            "transcript": "नमस्ते दुनिया",
            "language_code": "hi-IN",
            "timestamps": {
                "words": ["नमस्ते", "दुनिया"],
                "start_time_seconds": [0.0, 0.5],
                "end_time_seconds": [0.5, 1.0],
            }
        }
        a, t = make_adapter(resp)
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mktemp(suffix=".wav"))
        tmp.write_bytes(b"fake audio")
        try:
            out = a.transcribe("saaras:v4", str(tmp), {"language_code": "hi-IN", "with_timestamps": True})
        finally:
            tmp.unlink(missing_ok=True)
        self.assertEqual(t.last["method"], "POST")
        self.assertIn("/speech-to-text", t.last["url"])
        self.assertEqual(t.last["headers"]["api-subscription-key"], "sarvam-test-key-123456789012")
        self.assertIn("multipart/form-data", t.last["headers"]["Content-Type"])
        self.assertEqual(out["text"], "नमस्ते दुनिया")
        self.assertEqual(len(out["words"]), 2)
        self.assertEqual(out["words"][0]["text"], "नमस्ते")
        self.assertEqual(out["words"][0]["start"], 0.0)
        self.assertEqual(out["words"][0]["end"], 0.5)

    def test_transcribe_without_timestamps(self):
        resp = {"request_id": "req-123", "transcript": "Hello", "language_code": "en-IN"}
        a, t = make_adapter(resp)
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mktemp(suffix=".wav"))
        tmp.write_bytes(b"fake audio")
        try:
            out = a.transcribe("saaras:v4", str(tmp))
        finally:
            tmp.unlink(missing_ok=True)
        self.assertEqual(out["text"], "Hello")
        self.assertEqual(out["words"], [])

    def test_transcribe_auth_error(self):
        a, t = make_adapter(AuthError("bad key"))
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mktemp(suffix=".wav"))
        tmp.write_bytes(b"fake audio")
        try:
            with self.assertRaises(AuthError):
                a.transcribe("saaras:v4", str(tmp))
        finally:
            tmp.unlink(missing_ok=True)

    def test_transcribe_rate_limit(self):
        a, t = make_adapter(Retryable("429"))
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mktemp(suffix=".wav"))
        tmp.write_bytes(b"fake audio")
        try:
            with self.assertRaises(Retryable):
                a.transcribe("saaras:v4", str(tmp))
        finally:
            tmp.unlink(missing_ok=True)

    def test_transcribe_rejected(self):
        a, t = make_adapter(Rejected("file format not supported"))
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mktemp(suffix=".wav"))
        tmp.write_bytes(b"fake audio")
        try:
            with self.assertRaises(Rejected):
                a.transcribe("saaras:v4", str(tmp))
        finally:
            tmp.unlink(missing_ok=True)

    def test_transcribe_with_keyterms(self):
        resp = {"request_id": "req-123", "transcript": "Sarvam AI", "language_code": "en-IN"}
        a, t = make_adapter(resp)
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mktemp(suffix=".wav"))
        tmp.write_bytes(b"fake audio")
        try:
            out = a.transcribe("saaras:v4", str(tmp), {"keyterms": ["Sarvam", "AI"]})
        finally:
            tmp.unlink(missing_ok=True)
        # Check keyterms was sent as JSON
        body = t.last["body"]
        self.assertIn("keyterms", body)
        self.assertIn("Sarvam", body)

    # -------------------------- list_voices --------------------------
    def test_list_voices(self):
        a, t = make_adapter()
        got = a.list_voices()
        # Should have v3 speakers + v2 speakers + v4 note
        self.assertGreater(len(got), 30)
        # Check v3 speakers present
        v3_speakers = [v for v in got if v.get("model") == "bulbul:v3"]
        self.assertGreater(len(v3_speakers), 20)
        # Check v2 speakers present
        v2_speakers = [v for v in got if v.get("model") == "bulbul:v2"]
        self.assertEqual(len(v2_speakers), 7)
        # Check Tamil support documented
        for v in v3_speakers:
            self.assertIn("ta-IN", v.get("languages", []))


if __name__ == "__main__":
    unittest.main()