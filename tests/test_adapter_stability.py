"""Tests for the Stability AI adapter (Stable Audio) with the fake transport."""
import unittest
from aistudio.providers import config as C
from aistudio.providers.adapters.stability import StabilityAdapter
from aistudio.providers.base import AuthError, Rejected, Retryable
from tests._adapter_helpers import FakeTransport

CONN = {"id": "st", "type": "stability", "secret": {"api_key": "sk-stability-secret-123"}}
BASE = "https://api.stability.ai"
AUDIO = b"FAKE_MP3_DATA_" + b"x" * 32


def make(*answers):
    t = FakeTransport(*answers)
    return StabilityAdapter(CONN, transport=t, sleep=lambda s: None), t


class TestStability(unittest.TestCase):
    # -------------------------- registration --------------------------
    def test_registered(self):
        meta = C.PROVIDER_TYPES["stability"]
        self.assertEqual(meta["fields"], ["api_key"])
        self.assertEqual(C.capabilities_of("stability"), ["music", "sfx"])

    # -------------------------- list_models --------------------------
    def test_list_models(self):
        a, t = make()
        models = a.list_models()
        self.assertEqual({m["id"] for m in models},
                         {"stable-audio-2.5", "stable-audio-2", "stable-audio-3"})
        self.assertEqual({m["capability"] for m in models}, {"music", "sfx"})
        self.assertEqual(t.calls, [])            # a free call, but no request

    # -------------------------- test() --------------------------
    def test_test_ok(self):
        a, t = make({"id": "user-1", "email": "a@b.c"})
        res = a.test()
        self.assertTrue(res["ok"])
        self.assertEqual(t.last["method"], "GET")
        self.assertEqual(t.last["url"], BASE + "/v1/user/account")
        self.assertEqual(t.last["headers"]["Authorization"], "Bearer sk-stability-secret-123")

    def test_test_fail_scrubs_the_key(self):
        a, t = make(AuthError("HTTP 401: the key sk-stability-secret-123 is not valid"))
        res = a.test()
        self.assertFalse(res["ok"])
        self.assertNotIn("sk-stability-secret-123", res["message"])
        self.assertIn("***", res["message"])

    def test_test_without_a_key(self):
        a = StabilityAdapter({"id": "st", "type": "stability", "secret": {}}, transport=FakeTransport())
        res = a.test()
        self.assertFalse(res["ok"])
        self.assertIn("no API key", res["message"])

    # -------------------------- music --------------------------
    def test_music_happy(self):
        a, t = make(AUDIO)
        out = a.music("stable-audio-2.5", "a calm piano piece", 30)
        self.assertEqual(t.last["method"], "POST")
        self.assertEqual(t.last["url"], BASE + "/v2beta/audio/stable-audio-2/text-to-audio")
        self.assertEqual(t.last["headers"]["Accept"], "audio/*")
        self.assertTrue(t.last["headers"]["Content-Type"].startswith("multipart/form-data; boundary="))
        self.assertEqual(t.last["headers"]["Authorization"], "Bearer sk-stability-secret-123")
        body = t.last["body"]
        self.assertIsInstance(body, bytes)
        self.assertIn(b'name="prompt"\r\n\r\na calm piano piece\r\n', body)
        self.assertIn(b'name="model"\r\n\r\nstable-audio-2.5\r\n', body)
        self.assertIn(b'name="duration"\r\n\r\n30\r\n', body)
        self.assertIn(b'name="output_format"\r\n\r\nmp3\r\n', body)
        self.assertEqual(out["bytes"], AUDIO)
        self.assertEqual(out["mime"], "audio/mpeg")
        self.assertEqual(out["model"], "stable-audio-2.5")
        self.assertIsNone(out["cost"])

    def test_music_options(self):
        a, t = make(AUDIO)
        out = a.music("stable-audio-2", "thunder", 5,
                      {"output_format": "wav", "seed": 42, "steps": 30, "cfg_scale": 7})
        body = t.last["body"]
        self.assertIn(b'name="output_format"\r\n\r\nwav\r\n', body)
        self.assertIn(b'name="seed"\r\n\r\n42\r\n', body)
        self.assertIn(b'name="steps"\r\n\r\n30\r\n', body)
        self.assertIn(b'name="cfg_scale"\r\n\r\n7\r\n', body)
        self.assertEqual(out["mime"], "audio/wav")

    def test_music_rejects_an_unknown_format(self):
        a, t = make()
        with self.assertRaises(Rejected):
            a.music("stable-audio-2.5", "p", 5, {"output_format": "ogg"})

    # -------------------------- sfx --------------------------
    def test_sfx_uses_the_same_endpoint(self):
        a, t = make(AUDIO)
        out = a.sfx("stable-audio-2.5", "glass breaking", 2)
        self.assertEqual(t.last["url"], BASE + "/v2beta/audio/stable-audio-2/text-to-audio")
        self.assertIn(b'name="prompt"\r\n\r\nglass breaking\r\n', t.last["body"])
        self.assertEqual(out["bytes"], AUDIO)

    # -------------------------- the async model (Stable Audio 3) --------------------------
    def test_async_model_polls_the_result(self):
        a, t = make({"id": "abc123"}, b"", AUDIO)
        out = a.music("stable-audio-3", "epic strings", 30)
        self.assertEqual(t.calls[0]["url"], BASE + "/v2beta/audio/stable-audio/text-to-audio")
        self.assertEqual(t.calls[1]["url"], BASE + "/v2beta/audio/results/abc123")
        self.assertEqual(t.calls[2]["url"], BASE + "/v2beta/audio/results/abc123")
        self.assertEqual(out["bytes"], AUDIO)
        self.assertEqual(out["model"], "stable-audio-3")

    def test_async_times_out(self):
        a, t = make({"id": "abc123"}, b"", b"", b"")
        with self.assertRaises(Retryable):
            a.music("stable-audio-3", "p", 10, {"max_polls": 3})

    def test_async_without_an_id(self):
        a, t = make({})
        with self.assertRaises(Retryable):
            a.music("stable-audio-3", "p", 10)

    # -------------------------- errors --------------------------
    def test_auth_error(self):
        a, t = make(AuthError("HTTP 401"))
        with self.assertRaises(AuthError):
            a.music("stable-audio-2.5", "p", 5)

    def test_rate_limit(self):
        a, t = make(Retryable("HTTP 429"))
        with self.assertRaises(Retryable):
            a.sfx("stable-audio-2.5", "p", 5)

    def test_rejected(self):
        a, t = make(Rejected("HTTP 400: prompt: is required"))
        with self.assertRaises(Rejected):
            a.music("stable-audio-2.5", "p", 5)

    def test_no_key_raises_before_the_call(self):
        a = StabilityAdapter({"id": "st", "type": "stability", "secret": {}}, transport=FakeTransport())
        with self.assertRaises(AuthError):
            a.music("stable-audio-2.5", "p", 5)

    def test_the_key_is_never_in_the_request_body(self):
        a, t = make(AUDIO)
        a.music("stable-audio-2.5", "p", 5)
        self.assertNotIn(b"sk-stability-secret-123", t.last["body"])


if __name__ == "__main__":
    unittest.main()
