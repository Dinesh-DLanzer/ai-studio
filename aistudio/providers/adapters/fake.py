"""Built-in test provider: every capability, deterministic, no network, no key.  Used in test mode and by tests.

Model ids that start with "fail-" raise on purpose so fallback chains can be tested:
  fail-retry -> Retryable, fail-auth -> AuthError, fail-reject -> Rejected, fail-missing -> NotFound.
"""
import json
import struct

from aistudio.providers import fake as legacy
from aistudio.providers.base import Adapter, AuthError, NotFound, Rejected, Retryable

_FAILS = {"fail-retry": Retryable, "fail-auth": AuthError, "fail-reject": Rejected, "fail-missing": NotFound}


def _maybe_fail(model):
    if model in _FAILS:
        raise _FAILS[model](f"fake failure for {model}")


class FakeAdapter(Adapter):
    type = "fake"
    capabilities = frozenset({"chat", "vision", "image", "video"})

    def __init__(self, conn=None, transport=None):
        super().__init__(conn or {"id": "fake", "type": "fake"}, transport=lambda *a, **k: {})

    def list_models(self):
        return [{"id": "fake/llm", "name": "Fake chat", "capability": "chat"}, {"id": "fake/vision", "name": "Fake vision", "capability": "vision"},
                {"id": "fake/image", "name": "Fake image", "capability": "image"}, {"id": "fake/video", "name": "Fake video", "capability": "video"}]

    def test(self):
        return {"ok": True, "message": "Built-in test provider (free, no network)"}

    def chat(self, model, messages, opts=None):
        _maybe_fail(model)
        last = next((m["content"] for m in reversed(messages) if m.get("role") == "user" and isinstance(m.get("content"), str)), "")
        return {"text": "FAKE: " + last[:40], "usage": {"input": len(last), "output": 8}, "cost": 0.0, "model": model}

    def vision(self, model, prompt, images, opts=None):
        _maybe_fail(model)
        bad = (opts or {}).get("inject") == "extra_person"
        review = ({"verdict": "fail", "findings": [{"frame": 0, "issue": "extra person", "severity": "high"}], "summary": "extra person detected"}
                  if bad else {"verdict": "pass", "findings": [], "summary": "ok"})
        return {"text": json.dumps(review), "usage": {"input": 0, "output": 0}, "cost": 0.001, "model": model}

    def image(self, model, prompt, refs=(), aspect_ratio="9:16", opts=None):
        _maybe_fail(model)
        if len(refs) > legacy.MAX_REFS:
            raise Rejected("at most %d reference images" % legacy.MAX_REFS)
        return {"bytes": legacy.PNG_1X1, "usage": {}, "cost": legacy.FakeImageProvider.price, "model": model}

    def video_submit(self, model, req):
        _maybe_fail(model)
        if int(req["seconds"]) not in legacy.ALLOWED_SECONDS:
            raise Rejected("seconds must be one of %s" % (legacy.ALLOWED_SECONDS,))
        tag = "fail" if "FAIL_ME" in req.get("prompt", "") else "ok"
        return {"job_id": f"fake-{tag}-{int(req['seconds'])}-{'A' if req.get('audio') else 'S'}", "model": model}

    def video_poll(self, job):
        _, tag, secs, a = job["job_id"].split("-")
        if tag == "fail":
            return {"status": "failed", "error": "rejected by fake provider", "cost": 0.0}
        rate = legacy.FakeVideoProvider.price_per_second_audio if a == "A" else legacy.FakeVideoProvider.price_per_second_silent
        return {"status": "done", "error": None, "cost": round(int(secs) * rate, 6)}

    def video_download(self, job):
        _, _, secs, a = job["job_id"].split("-")
        return b"FAKEMP4" + struct.pack(">B", int(secs)) + (b"A" if a == "A" else b"S")
