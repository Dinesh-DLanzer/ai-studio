"""E8: deterministic fake providers for tests.  NO network, NO randomness, standard library only.

Contract (tests in tests/test_fake.py).  Every provider method returns a dict, never raises for valid input.
  class FakeImageProvider:   price = 0.036
      generate(prompt: str, refs: list[str] = (), aspect_ratio: str = "9:16") -> dict
        -> {"bytes": <valid PNG bytes>, "cost": 0.036, "model": "fake/image"}.  The PNG must be a real, decodable
           1x1 PNG (use zlib+struct, no external libs).  Same inputs -> identical bytes.  More than 4 refs raises ValueError.
  class FakeVideoProvider:   price_per_second_audio = 0.05 ; price_per_second_silent = 0.03
      generate(prompt: str, seconds: int, audio: bool = False, first_frame: str | None = None) -> dict
        -> {"bytes": <non-empty bytes starting with b"FAKEMP4">, "cost": round(seconds * rate, 6),
            "model": "fake/video", "seconds": seconds}.  seconds must be one of 4, 6, 8 else ValueError.
        If the prompt contains the text "FAIL_ME" the result is {"error": "rejected by fake provider", "cost": 0.0}.
  class FakeVisionProvider:
      review(frames: list[str], context: dict | None = None) -> dict
        -> {"verdict": "pass", "findings": [], "summary": "ok", "cost": 0.001, "model": "fake/vision"}.
        If context has {"inject": "extra_person"} the verdict is "fail" and findings is
        [{"frame": 0, "issue": "extra person", "severity": "high"}].
  class FakeLLM:
      complete(prompt: str) -> dict -> {"text": "FAKE: " + prompt[:40], "cost": 0.0, "model": "fake/llm"}
"""

import struct
import zlib

MAX_REFS = 4
ALLOWED_SECONDS = (4, 6, 8)
MODEL_IMAGE = "fake/image"
MODEL_VIDEO = "fake/video"
MODEL_VISION = "fake/vision"
MODEL_LLM = "fake/llm"


def _chunk(typ, data):
    return struct.pack(">I", len(data)) + typ + data + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)


def _png_1x1():
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\x00\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


PNG_1X1 = _png_1x1()


class FakeImageProvider:
    price = 0.036

    def generate(self, prompt, refs=(), aspect_ratio="9:16"):
        if len(refs) > MAX_REFS:
            raise ValueError("fake image provider accepts at most %d refs, got %d" % (MAX_REFS, len(refs)))
        return {"bytes": PNG_1X1, "cost": self.price, "model": MODEL_IMAGE}


class FakeVideoProvider:
    price_per_second_audio = 0.05
    price_per_second_silent = 0.03

    def generate(self, prompt, seconds, audio=False, first_frame=None):
        if seconds not in ALLOWED_SECONDS:
            raise ValueError("fake video provider: seconds must be one of %s, got %r" % (ALLOWED_SECONDS, seconds))
        if "FAIL_ME" in prompt:
            return {"error": "rejected by fake provider", "cost": 0.0}
        rate = self.price_per_second_audio if audio else self.price_per_second_silent
        payload = b"FAKEMP4" + struct.pack(">B", seconds) + (b"A" if audio else b"S")
        return {
            "bytes": payload,
            "cost": round(seconds * rate, 6),
            "model": MODEL_VIDEO,
            "seconds": seconds,
        }


class FakeVisionProvider:
    def review(self, frames, context=None):
        context = context or {}
        if context.get("inject") == "extra_person":
            return {
                "verdict": "fail",
                "findings": [{"frame": 0, "issue": "extra person", "severity": "high"}],
                "summary": "extra person detected",
                "cost": 0.001,
                "model": MODEL_VISION,
            }
        return {"verdict": "pass", "findings": [], "summary": "ok", "cost": 0.001, "model": MODEL_VISION}


class FakeLLM:
    def complete(self, prompt):
        return {"text": "FAKE: " + prompt[:40], "cost": 0.0, "model": MODEL_LLM}