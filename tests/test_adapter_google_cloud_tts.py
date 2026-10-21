"""Tests for Google Cloud TTS adapter using FakeTransport."""
import base64
import unittest
from aistudio.providers.adapters.google_cloud_tts import GoogleCloudTTSAdapter
from aistudio.providers.base import Retryable, AuthError, Rejected, NotFound
from tests._adapter_helpers import FakeTransport


CONN = {"id": "gctts", "type": "google_cloud_tts", "secret": {"api_key": "AIzaTestKey12345678901234567890"}}
AUDIO_BYTES = b"FAKE_MP3_DATA_" + b"x" * 100
B64_AUDIO = base64.b64encode(AUDIO_BYTES).decode()


def make_adapter(*answers):
    t = FakeTransport(*answers)
    return GoogleCloudTTSAdapter(CONN, transport=t), t


class TestGoogleCloudTTSAdapter(unittest.TestCase):
    # -------------------------- list_models --------------------------
    def test_list_models(self):
        voices_resp = {"voices": [
            {"name": "en-US-Standard-A", "languageCodes": ["en-US"], "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
            {"name": "ta-IN-Standard-A", "languageCodes": ["ta-IN"], "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
            {"name": "en-US-Wavenet-D", "languageCodes": ["en-US"], "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
        ]}
        a, t = make_adapter(voices_resp)
        got = a.list_models()
        self.assertEqual(t.last["url"], "https://texttospeech.googleapis.com/v1/voices?key=AIzaTestKey12345678901234567890")
        self.assertEqual(len(got), 3)
        self.assertEqual(got[0]["id"], "en-US-Standard-A")
        self.assertEqual(got[0]["capability"], "tts")
        self.assertEqual(got[1]["language_codes"], ["ta-IN"])

    # -------------------------- test() --------------------------
    def test_test_ok(self):
        a, t = make_adapter({"voices": []})
        res = a.test()
        self.assertTrue(res["ok"])
        self.assertIn("voices", t.last["url"])

    def test_test_fail(self):
        a, t = make_adapter(AuthError("invalid api key"))
        res = a.test()
        self.assertFalse(res["ok"])
        self.assertIn("invalid api key", res["message"].lower())

    # -------------------------- tts --------------------------
    def test_tts_happy(self):
        a, t = make_adapter({"audioContent": B64_AUDIO})
        out = a.tts("en-US-Standard-A", "Hello world", "en-US-Standard-A")
        self.assertEqual(t.last["method"], "POST")
        self.assertIn("/v1/text:synthesize?key=AIzaTestKey12345678901234567890", t.last["url"])
        self.assertEqual(t.last["body"]["input"]["text"], "Hello world")
        self.assertEqual(t.last["body"]["voice"]["name"], "en-US-Standard-A")
        self.assertEqual(t.last["body"]["audioConfig"]["audioEncoding"], "MP3")
        self.assertEqual(out["bytes"], AUDIO_BYTES)
        self.assertEqual(out["mime"], "audio/mpeg")
        self.assertEqual(out["model"], "en-US-Standard-A")

    def test_tts_with_options(self):
        a, t = make_adapter({"audioContent": B64_AUDIO})
        a.tts("m", "text", "v", {"audio_encoding": "LINEAR16", "speaking_rate": 1.2, "pitch": 2.0, "volume_gain_db": 3.0, "sample_rate_hertz": 48000})
        self.assertEqual(t.last["body"]["audioConfig"]["audioEncoding"], "LINEAR16")
        self.assertEqual(t.last["body"]["audioConfig"]["speakingRate"], 1.2)
        self.assertEqual(t.last["body"]["audioConfig"]["pitch"], 2.0)
        self.assertEqual(t.last["body"]["audioConfig"]["volumeGainDb"], 3.0)
        self.assertEqual(t.last["body"]["audioConfig"]["sampleRateHertz"], 48000)

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
        from aistudio.providers.base import scrub
        secret = {"api_key": "AIzaTestKey12345678901234567890"}
        msg = scrub("Error: AIzaTestKey12345678901234567890 leaked", secret)
        self.assertNotIn("AIzaTestKey12345678901234567890", msg)
        self.assertIn("***", msg)

    # -------------------------- list_voices --------------------------
    def test_list_voices(self):
        voices_resp = {"voices": [
            {"name": "v1", "languageCodes": ["en-US"], "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
            {"name": "v2", "languageCodes": ["ta-IN"], "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
        ]}
        a, t = make_adapter(voices_resp)
        got = a.list_voices()
        self.assertEqual(t.last["url"], "https://texttospeech.googleapis.com/v1/voices?key=AIzaTestKey12345678901234567890")
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0]["name"], "v1")
        self.assertEqual(got[1]["languageCodes"], ["ta-IN"])


if __name__ == "__main__":
    unittest.main()