"""Tests for the Cartesia adapter (TTS and voice cloning) with the fake transport."""
import tempfile
import unittest
from pathlib import Path
from aistudio.providers import config as C
from aistudio.providers.adapters.cartesia import CartesiaAdapter
from aistudio.providers.base import AuthError, Rejected, Retryable
from tests._adapter_helpers import FakeTransport

CONN = {"id": "ca", "type": "cartesia", "secret": {"api_key": "sk_car_secret_123"}}
BASE = "https://api.cartesia.ai"
AUDIO = b"FAKE_WAV_DATA_" + b"x" * 32
VOICE = "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"


def make(*answers):
    t = FakeTransport(*answers)
    return CartesiaAdapter(CONN, transport=t), t


def clip_file(name="clip.mp3", data=b"FAKEAUDIO"):
    p = Path(tempfile.mkdtemp()) / name
    p.write_bytes(data)
    return str(p)


class TestCartesia(unittest.TestCase):
    # -------------------------- registration --------------------------
    def test_registered(self):
        meta = C.PROVIDER_TYPES["cartesia"]
        self.assertEqual(meta["fields"], ["api_key"])
        self.assertEqual(C.capabilities_of("cartesia"), ["tts", "voice_clone"])

    # -------------------------- list_models --------------------------
    def test_list_models(self):
        a, t = make()
        models = a.list_models()
        self.assertEqual([m["id"] for m in models], ["sonic-3.6", "sonic-3.5", "sonic-3", "sonic-latest"])
        self.assertEqual({m["capability"] for m in models}, {"tts"})
        self.assertEqual(t.calls, [])

    # -------------------------- test() --------------------------
    def test_test_ok(self):
        a, t = make({"data": [], "has_more": False})
        res = a.test()
        self.assertTrue(res["ok"])
        self.assertEqual(t.last["method"], "GET")
        self.assertEqual(t.last["url"], BASE + "/voices?limit=1")
        self.assertEqual(t.last["headers"]["Authorization"], "Bearer sk_car_secret_123")
        self.assertEqual(t.last["headers"]["Cartesia-Version"], "2026-08-14")

    def test_test_fail_scrubs_the_key(self):
        a, t = make(AuthError("HTTP 401: the key sk_car_secret_123 is not valid"))
        res = a.test()
        self.assertFalse(res["ok"])
        self.assertNotIn("sk_car_secret_123", res["message"])
        self.assertIn("***", res["message"])

    def test_test_without_a_key(self):
        a = CartesiaAdapter({"id": "ca", "type": "cartesia", "secret": {}}, transport=FakeTransport())
        res = a.test()
        self.assertFalse(res["ok"])
        self.assertIn("no API key", res["message"])

    # -------------------------- tts --------------------------
    def test_tts_happy(self):
        a, t = make(AUDIO)
        out = a.tts("sonic-3.6", "Hello there", VOICE)
        self.assertEqual(t.last["method"], "POST")
        self.assertEqual(t.last["url"], BASE + "/tts/bytes")
        self.assertEqual(t.last["headers"]["Authorization"], "Bearer sk_car_secret_123")
        self.assertEqual(t.last["headers"]["Cartesia-Version"], "2026-08-14")
        self.assertEqual(t.last["body"]["model_id"], "sonic-3.6")
        self.assertEqual(t.last["body"]["transcript"], "Hello there")
        self.assertEqual(t.last["body"]["voice"], VOICE)
        self.assertEqual(t.last["body"]["output_format"],
                         {"container": "mp3", "sample_rate": 44100, "bit_rate": 128000})
        self.assertEqual(out["bytes"], AUDIO)
        self.assertEqual(out["mime"], "audio/mpeg")
        self.assertEqual(out["model"], "sonic-3.6")
        self.assertIsNone(out["cost"])

    def test_tts_options(self):
        a, t = make(AUDIO)
        a.tts("sonic-3", "வணக்கம்", VOICE,
              {"language": "ta", "generation_config": {"speed": 1.1, "volume": 0.9}})
        self.assertEqual(t.last["body"]["language"], "ta")
        self.assertEqual(t.last["body"]["generation_config"], {"speed": 1.1, "volume": 0.9})

    def test_tts_with_a_voice_object(self):
        a, t = make(AUDIO)
        a.tts("sonic-3.6", "hi", {"id": "v9"})
        self.assertEqual(t.last["body"]["voice"], {"id": "v9"})

    def test_tts_with_a_wav_format(self):
        a, t = make(AUDIO)
        out = a.tts("sonic-3.6", "hi", VOICE,
                    {"output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 44100}})
        self.assertEqual(out["mime"], "audio/wav")

    def test_tts_needs_a_voice(self):
        a, t = make(AUDIO)
        with self.assertRaises(Rejected):
            a.tts("sonic-3.6", "hi", "")

    def test_tts_rejects_a_bad_output_format(self):
        a, t = make(AUDIO)
        with self.assertRaises(Rejected):
            a.tts("sonic-3.6", "hi", VOICE, {"output_format": {"sample_rate": 44100}})

    # -------------------------- voice clone --------------------------
    def test_voice_clone_happy(self):
        clip = clip_file()
        a, t = make({"id": "v-123", "name": "Nila", "language": "ta", "access": "private"})
        out = a.voice_clone("Nila", clip, "ta", {"tagline": "warm", "access": "private"})
        self.assertEqual(t.last["method"], "POST")
        self.assertEqual(t.last["url"], BASE + "/voices/clone")
        self.assertTrue(t.last["headers"]["Content-Type"].startswith("multipart/form-data; boundary="))
        body = t.last["body"]
        self.assertIn(b'name="name"\r\n\r\nNila\r\n', body)
        self.assertIn(b'name="language"\r\n\r\nta\r\n', body)
        self.assertIn(b'name="tagline"\r\n\r\nwarm\r\n', body)
        self.assertIn(b'name="access"\r\n\r\nprivate\r\n', body)
        self.assertIn(b'filename="clip.mp3"', body)
        self.assertIn(b"FAKEAUDIO", body)
        self.assertEqual(out["voice_id"], "v-123")
        self.assertEqual(out["name"], "Nila")
        self.assertEqual(out["language"], "ta")

    def test_voice_clone_missing_file(self):
        a, t = make()
        with self.assertRaises(Rejected):
            a.voice_clone("Nila", "/nope/clip.mp3", "ta")

    def test_voice_clone_needs_a_name_and_a_language(self):
        clip = clip_file()
        a, t = make()
        with self.assertRaises(Rejected):
            a.voice_clone("", clip, "ta")
        with self.assertRaises(Rejected):
            a.voice_clone("Nila", clip, "")

    def test_voice_clone_without_a_voice_id(self):
        clip = clip_file()
        a, t = make({})
        with self.assertRaises(Retryable):
            a.voice_clone("Nila", clip, "ta")

    # -------------------------- voices --------------------------
    def test_list_voices(self):
        a, t = make({"data": [{"id": "v1", "name": "Skylar"}], "has_more": False})
        voices = a.list_voices({"limit": 10, "language": "ta"})
        self.assertEqual(voices[0]["id"], "v1")
        self.assertIn("limit=10", t.last["url"])
        self.assertIn("language=ta", t.last["url"])

    # -------------------------- errors --------------------------
    def test_auth_error(self):
        a, t = make(AuthError("HTTP 401"))
        with self.assertRaises(AuthError):
            a.tts("sonic-3.6", "hi", VOICE)

    def test_rate_limit(self):
        a, t = make(Retryable("HTTP 429"))
        with self.assertRaises(Retryable):
            a.tts("sonic-3.6", "hi", VOICE)

    def test_rejected(self):
        a, t = make(Rejected("HTTP 400: transcript: is required"))
        with self.assertRaises(Rejected):
            a.tts("sonic-3.6", "hi", VOICE)

    def test_no_key_raises_before_the_call(self):
        a = CartesiaAdapter({"id": "ca", "type": "cartesia", "secret": {}}, transport=FakeTransport())
        with self.assertRaises(AuthError):
            a.tts("sonic-3.6", "hi", VOICE)

    def test_the_key_is_never_in_the_request_body(self):
        a, t = make(AUDIO)
        a.tts("sonic-3.6", "hi", VOICE)
        self.assertNotIn("sk_car_secret_123", str(t.last["body"]))


if __name__ == "__main__":
    unittest.main()
