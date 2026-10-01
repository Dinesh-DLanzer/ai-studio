"""Real providers over OpenRouter (Qwen Image 3, Veo 3.1 Lite, a vision model). Standard library only.

All network access goes through one injectable `transport(method, path, body=None, raw=False)`, so tests never touch the
network. The default transport reads the key from an environment variable (never logged, never returned).
These classes are ONLY used after a human-approved proposal (see approvals.py / service.py).
"""
import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from aistudio.vision.clip_checklist import parse_review

API = "https://openrouter.ai/api/v1"


from aistudio.providers.base import ProviderError      # one error class for old and new code


def _stored_key(ref="openrouter"):
    """The OpenRouter key saved in AI Studio (Settings > AI Providers). Keys are never read from the environment or a .env file."""
    from aistudio.secrets import SecretStore
    return SecretStore().get(ref).get("api_key", "")


def default_transport(timeout=120, secret_ref="openrouter"):
    def transport(method, path, body=None, raw=False):
        if os.environ.get("AISTUDIO_NO_NETWORK") == "1":     # kill switch (tests, CI, offline work)
            raise ProviderError("network disabled by AISTUDIO_NO_NETWORK=1")
        key = _stored_key(secret_ref)
        if not key:
            raise ProviderError("No OpenRouter key saved. Open AI Studio > Settings > AI Providers and add OpenRouter.")
        req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                return data if raw else json.loads(data)
        except urllib.error.HTTPError as e:
            hint = " The API key was rejected: replace it in Settings > AI Providers and make sure it is a real key with credit." if e.code in (401, 403) else ""
            raise ProviderError(f"HTTP {e.code} from {path}: {e.read().decode(errors='replace')[:300]}{hint}") from None
        except urllib.error.URLError as e:
            raise ProviderError(f"network error: {e.reason}") from None
    return transport


def data_url(path):
    p = Path(path)
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


class OpenRouterImage:
    """Qwen Image 3 via /images. refs = local image paths (max 4)."""

    def __init__(self, model="qwen/qwen-image-3", transport=None, resolution="2K"):
        self.model, self.transport, self.resolution = model, transport or default_transport(), resolution

    def generate(self, prompt, refs=(), aspect_ratio="9:16"):
        if len(refs) > 4:
            raise ValueError("at most 4 reference images")
        body = {"model": self.model, "prompt": prompt, "aspect_ratio": aspect_ratio, "resolution": self.resolution, "n": 1,
                "input_references": [{"type": "image_url", "image_url": {"url": data_url(r)}} for r in refs]}
        r = self.transport("POST", "/images", body)
        items = r.get("data") or []
        if not items or not items[0].get("b64_json"):
            raise ProviderError("no image in response")
        return {"bytes": base64.b64decode(items[0]["b64_json"]), "cost": float((r.get("usage") or {}).get("cost") or 0),
                "model": self.model}


class OpenRouterVideo:
    """Veo 3.1 Lite via /videos: submit, poll, download. Returns {"pending": True, ...} on timeout so the job can be synced."""

    def __init__(self, model="google/veo-3.1-lite", transport=None, resolution="720p", aspect_ratio="9:16",
                 poll_seconds=10, timeout_seconds=1500, sleep=time.sleep, clock=time.time):
        self.model, self.transport, self.resolution, self.aspect = model, transport or default_transport(), resolution, aspect_ratio
        self.poll, self.timeout, self.sleep, self.clock = poll_seconds, timeout_seconds, sleep, clock

    def generate(self, prompt, seconds, audio=False, first_frame=None):
        body = {"model": self.model, "prompt": prompt, "duration": seconds, "resolution": self.resolution,
                "aspect_ratio": self.aspect, "generate_audio": bool(audio)}
        if first_frame:
            body["frame_images"] = [{"type": "image_url", "image_url": {"url": data_url(first_frame)}, "frame_type": "first_frame"}]
        job = self.transport("POST", "/videos", body)
        jid, status, t0, poll = job["id"], job.get("status"), self.clock(), job
        while status not in ("completed", "failed"):
            if self.clock() - t0 > self.timeout:
                return {"pending": True, "job_id": jid, "cost": 0.0, "model": self.model, "seconds": seconds}
            self.sleep(self.poll)
            poll = self.transport("GET", f"/videos/{jid}")
            status = poll.get("status")
        cost = float((poll.get("usage") or {}).get("cost") or 0)
        if status == "failed":
            return {"error": str(poll.get("error") or "generation failed"), "cost": cost, "job_id": jid}
        data = self.transport("GET", f"/videos/{jid}/content?index=0", raw=True)
        return {"bytes": data, "cost": cost, "model": self.model, "seconds": seconds, "job_id": jid}

    def fetch(self, job_id):
        """Resolve a job left pending by a timeout (used by `sync`)."""
        poll = self.transport("GET", f"/videos/{job_id}")
        if poll.get("status") not in ("completed", "failed"):
            return {"pending": True, "job_id": job_id, "cost": 0.0}
        cost = float((poll.get("usage") or {}).get("cost") or 0)
        if poll["status"] == "failed":
            return {"error": str(poll.get("error") or "failed"), "cost": cost, "job_id": job_id}
        return {"bytes": self.transport("GET", f"/videos/{job_id}/content?index=0", raw=True), "cost": cost, "job_id": job_id}


class OpenRouterVision:
    """A vision-capable chat model asked to follow the checklist prompt; the answer is parsed by parse_review."""

    def __init__(self, model="google/gemini-2.5-flash-lite", transport=None):
        self.model, self.transport = model, transport or default_transport()

    def review(self, frames, context=None):
        prompt = (context or {}).get("prompt", "Review these frames and answer as JSON.")
        content = [{"type": "text", "text": prompt}] + [{"type": "image_url", "image_url": {"url": data_url(f)}} for f in frames]
        r = self.transport("POST", "/chat/completions", {"model": self.model, "messages": [{"role": "user", "content": content}],
                                                          "usage": {"include": True}})
        text = ((r.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        out = parse_review(text)
        out.update({"cost": float((r.get("usage") or {}).get("cost") or 0), "model": self.model})
        return out


class OpenRouterLLM:
    """Chat completion over a chain of FREE models (tries the next one on a rate limit or error). Returns {"text", "model", "cost"}."""

    def __init__(self, models, transport=None, max_tokens=3500, allow_paid=None):
        from aistudio.chat import check_chat_models
        self.models, self.transport, self.max_tokens = check_chat_models(list(models), allow_paid), transport or default_transport(timeout=90), max_tokens

    def complete(self, messages):
        errors = []
        for m in self.models:
            try:
                r = self.transport("POST", "/chat/completions", {"model": m, "messages": messages, "max_tokens": self.max_tokens,
                                                                  "temperature": 0.4, "usage": {"include": True}})
                text = ((r.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                if not text.strip():
                    raise ProviderError("empty answer")
                return {"text": text, "model": m, "cost": float((r.get("usage") or {}).get("cost") or 0)}
            except ProviderError as e:
                errors.append(f"{m}: {str(e)[:90]}")
        raise ProviderError("all free chat models failed: " + " | ".join(errors))
