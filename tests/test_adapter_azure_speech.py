"""Tests for Azure Speech adapter using FakeTransport."""
import unittest
from aistudio.providers.adapters.azure_speech import AzureSpeechAdapter
from aistudio.providers.base import Retryable, AuthError, Rejected
from tests._adapter_helpers import FakeTransport


CONN = {"id": "az", "type": "azure_speech", "secret": {"api_key": "azure-test-key-12345", "region": "eastus"}}
AUDIO_BYTES = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"x" * 100


def make_adapter(*answers):
    t = FakeTransport(*answers)
    return AzureSpeechAdapter(CONN, transport=t), t


class TestAzureSpeechAdapter(unittest.TestCase):
    # -------------------------- list_models --------------------------
    def test_list_models(self):
        voices_resp = [
            {"ShortName": "en-US-JennyNeural", "DisplayName": "Jenny", "Locale": "en-US", "Gender": "Female", "VoiceType": "Neural", "StyleList": ["cheerful", "sad"], "SampleRateHertz": "48000"},
            {"ShortName": "ta-IN-PallaviNeural", "DisplayName": "Pallavi", "Locale": "ta-IN", "Gender": "Female", "VoiceType": "Neural", "StyleList": [], "SampleRateHertz": "48000"},
        ]
        a, t = make_adapter(voices_resp)
        got = a.list_models()
        self.assertEqual(t.last["url"], "https://eastus.tts.speech.microsoft.com/tts/cognitiveservices/voices/list")
        self.assertEqual(t.last["headers"]["Ocp-Apim-Subscription-Key"], "azure-test-key-12345")
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0]["id"], "en-US-JennyNeural")
        self.assertEqual(got[0]["capability"], "tts")
        self.assertEqual(got[1]["locale"], "ta-IN")

    # -------------------------- test() --------------------------
    def test_test_ok(self):
        a, t = make_adapter([{"ShortName": "v1"}])
        res = a.test()
        self.assertTrue(res["ok"])

    def test_test_fail(self):
        a, t = make_adapter(AuthError("bad key"))
        res = a.test()
        self.assertFalse(res["ok"])
        self.assertIn("bad key", res["message"].lower())

    # -------------------------- tts --------------------------
    def test_tts_happy(self):
        a, t = make_adapter(AUDIO_BYTES)
        out = a.tts("en-US-JennyNeural", "Hello world", "en-US-JennyNeural")
        self.assertEqual(t.last["method"], "POST")
        self.assertIn("cognitiveservices/v1", t.last["url"])
        self.assertEqual(t.last["headers"]["Ocp-Apim-Subscription-Key"], "azure-test-key-12345")
        self.assertEqual(t.last["headers"]["Content-Type"], "application/ssml+xml")
        self.assertIn("en-US-JennyNeural", t.last["body"].decode("utf-8"))
        self.assertIn("Hello world", t.last["body"].decode("utf-8"))
        self.assertEqual(out["bytes"], AUDIO_BYTES)
        self.assertEqual(out["mime"], "audio/wav")

    def test_tts_with_output_format(self):
        a, t = make_adapter(AUDIO_BYTES)
        a.tts("m", "text", "v", {"output_format": "audio-24khz-160kbitrate-mono-mp3"})
        self.assertEqual(t.last["headers"]["X-Microsoft-OutputFormat"], "audio-24khz-160kbitrate-mono-mp3")
        self.assertEqual(t.last["headers"]["Content-Type"], "application/ssml+xml")

    def test_tts_auth_error(self):
        a, t = make_adapter(AuthError("invalid key"))
        with self.assertRaises(AuthError):
            a.tts("m", "text", "v")

    def test_tts_rate_limit(self):
        a, t = make_adapter(Retryable("429 too many requests"))
        with self.assertRaises(Retryable):
            a.tts("m", "text", "v")

    def test_tts_rejected(self):
        a, t = make_adapter(Rejected("bad voice"))
        with self.assertRaises(Rejected):
            a.tts("m", "text", "v")

    def test_tts_secret_not_in_error(self):
        from aistudio.providers.base import scrub
        secret = {"api_key": "azure-test-key-12345"}
        msg = scrub("Error: azure-test-key-12345 leaked", secret)
        self.assertNotIn("azure-test-key-12345", msg)
        self.assertIn("***", msg)

    # -------------------------- transcribe --------------------------
    def test_transcribe_happy(self):
        resp = {
            "combinedPhrases": [{"text": "Hello world"}],
            "phrases": [
                {"text": "Hello", "offsetInTicks": 0, "durationInTicks": 5000000},
                {"text": "world", "offsetInTicks": 5000000, "durationInTicks": 5000000},
            ]
        }
        a, t = make_adapter(resp)
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mktemp(suffix=".wav"))
        tmp.write_bytes(b"fake audio")
        try:
            out = a.transcribe("saaras:v4", str(tmp), {"language_code": "en-US"})
        finally:
            tmp.unlink(missing_ok=True)
        self.assertEqual(t.last["method"], "POST")
        self.assertIn("/speechtotext/transcriptions:transcribe?api-version=2025-10-15", t.last["url"])
        self.assertEqual(t.last["headers"]["Ocp-Apim-Subscription-Key"], "azure-test-key-12345")
        self.assertIn("multipart/form-data", t.last["headers"]["Content-Type"])
        self.assertEqual(out["text"].strip(), "Hello world")
        self.assertEqual(len(out["words"]), 2)
        self.assertEqual(out["words"][0]["text"], "Hello")
        self.assertAlmostEqual(out["words"][0]["start"], 0.0)
        self.assertAlmostEqual(out["words"][0]["end"], 0.5)

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
        a, t = make_adapter(Rejected("file too large"))
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mktemp(suffix=".wav"))
        tmp.write_bytes(b"fake audio")
        try:
            with self.assertRaises(Rejected):
                a.transcribe("saaras:v4", str(tmp))
        finally:
            tmp.unlink(missing_ok=True)

    # -------------------------- list_voices --------------------------
    def test_list_voices(self):
        voices_resp = [
            {"ShortName": "v1", "DisplayName": "Voice 1", "Locale": "en-US", "Gender": "Female", "VoiceType": "Neural", "StyleList": [], "SampleRateHertz": "48000"},
        ]
        a, t = make_adapter(voices_resp)
        got = a.list_voices()
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["ShortName"], "v1")


if __name__ == "__main__":
    unittest.main()