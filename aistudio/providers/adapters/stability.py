"""Stability AI adapter (Stable Audio: music and sound effects).  Standard library only.

API shapes (verified against the Stability AI API reference on 2026-10-20,
https://docs.stability.ai/api-reference):
  type = "stability"
  capabilities = {"music", "sfx"}
  default_base_url = "https://api.stability.ai"
  Header on EVERY request: {"Authorization": "Bearer " + api_key}

Endpoints used here:
  POST /v2beta/audio/stable-audio-2/text-to-audio   (Stable Audio 2.0 and 2.5 - synchronous)
      multipart/form-data: prompt (required), model ("stable-audio-2" | "stable-audio-2.5"),
      duration (1-190 seconds), seed, steps, cfg_scale, output_format ("mp3" | "wav").
      Answer: 200 with the audio bytes (ask for them with Accept: audio/*).
  POST /v2beta/audio/stable-audio/text-to-audio     (Stable Audio 3.0 - asynchronous)
      the same fields, model "stable-audio-3", duration 1-380 seconds.
      Answer: 202 {"id": "<64 hex characters>"}.
  GET  /v2beta/audio/results/{id}                  (the result of an async generation)
      202 while it is still running, 200 with the audio bytes.  Results are kept for 24 hours.
  GET  /v1/user/account                            (free and authenticated: the account of the key)

Prices (from the docs, 1 credit = $0.01): Stable Audio 2.5 and 3.0 cost 8 credits per successful
generation, Stable Audio 2.0 costs 17 + 0.06 * steps credits.  The adapter never reports a cost
(cost is None): the dated price cards of plan 14 do that.

UNVERIFIED:
  - the body of the 202 answer of GET /v2beta/audio/results/{id}.  The transport does not hand the
    HTTP status code to the adapter, so an EMPTY body is read as "still running" and any bytes as
    "finished".  The docs only say that 202 means "in progress".
  - the cost of a generation in dollars: it is not in the response, so cost is always None.
  - "negative_prompt" belongs to the old stable-audio-1 endpoint and is not in the current schema,
    so it is never sent.
"""
import json
import time
import uuid

from aistudio.providers.base import Adapter, AuthError, Rejected, Retryable, scrub

MIME = {"mp3": "audio/mpeg", "wav": "audio/wav"}
SYNC_PATH = "/v2beta/audio/stable-audio-2/text-to-audio"
ASYNC_PATH = "/v2beta/audio/stable-audio/text-to-audio"
RESULT_PATH = "/v2beta/audio/results/"
ACCOUNT_PATH = "/v1/user/account"

# The Stable Audio models in the current API schema.  Stable Audio makes music AND sound effects
# from the same endpoint, so every model is listed under both capabilities.
MODELS = (("stable-audio-2.5", "Stable Audio 2.5"),
          ("stable-audio-2", "Stable Audio 2"),
          ("stable-audio-3", "Stable Audio 3"))


def multipart(fields):
    """Build a multipart/form-data body with text fields only.  Returns (bytes, content_type)."""
    boundary = "----aistudio" + uuid.uuid4().hex
    out = bytearray()
    for name, value in fields.items():
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += f"{value}\r\n".encode()
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


class StabilityAdapter(Adapter):
    type = "stability"
    capabilities = frozenset({"music", "sfx"})
    default_base_url = "https://api.stability.ai"

    def __init__(self, conn, transport=None, sleep=time.sleep):
        super().__init__(conn, transport)
        self.sleep = sleep

    # ---------------------------------------------------------------- helpers
    @property
    def _headers(self):
        return {"Authorization": "Bearer " + (self.secret.get("api_key") or "")}

    def _key(self):
        key = str(self.secret.get("api_key") or "").strip()
        if not key:
            raise AuthError("no API key for Stability AI")
        return key

    # ---------------------------------------------------------------- calls
    def list_models(self):
        """Stable Audio has no model list endpoint: the model ids come from the API schema."""
        out = []
        for mid, name in MODELS:
            out.append({"id": mid, "name": name, "capability": "music"})
            out.append({"id": mid, "name": name, "capability": "sfx"})
        return out

    def test(self):
        try:
            self._key()
            self.transport("GET", self.base_url + ACCOUNT_PATH, headers=self._headers)
            return {"ok": True, "message": "Connected successfully"}
        except Exception as e:
            return {"ok": False, "message": scrub(e, self.secret)[:200]}

    def music(self, model, prompt, seconds, opts=None):
        """Stable Audio music.  Returns {"bytes", "mime", "cost", "model"}."""
        return self._generate(model, prompt, seconds, opts)

    def sfx(self, model, prompt, seconds, opts=None):
        """Stable Audio sound effect.  Same endpoint as music.  Returns {"bytes", "mime", "cost", "model"}."""
        return self._generate(model, prompt, seconds, opts)

    # ---------------------------------------------------------------- internals
    def _generate(self, model, prompt, seconds, opts):
        opts = opts or {}
        self._key()
        model = str(model or opts.get("model") or "stable-audio-2.5")
        fmt = str(opts.get("output_format") or "mp3").lower()
        if fmt not in MIME:
            raise Rejected(f"output_format must be one of {', '.join(sorted(MIME))}")
        fields = {"prompt": prompt, "model": model, "output_format": fmt}
        if seconds is not None:
            fields["duration"] = int(seconds)
        for k in ("seed", "steps", "cfg_scale"):
            if opts.get(k) is not None:
                fields[k] = opts[k]
        body, content_type = multipart(fields)
        headers = {**self._headers, "Accept": "audio/*", "Content-Type": content_type}
        if model.startswith("stable-audio-3"):
            doc = self.transport("POST", self.base_url + ASYNC_PATH, headers=headers, body=body)
            doc = doc if isinstance(doc, dict) else json.loads(doc or "{}")
            gid = doc.get("id")
            if not gid:
                raise Retryable("Stability AI did not return a generation id")
            return self._await(self.base_url + RESULT_PATH + str(gid), fmt, model, opts)
        blob = self.transport("POST", self.base_url + SYNC_PATH, headers=headers, body=body, raw=True)
        return {"bytes": blob, "mime": MIME[fmt], "cost": None, "model": model}

    def _await(self, url, fmt, model, opts):
        """Poll an async generation.  An empty body means "still running" (see the docstring)."""
        for i in range(int(opts.get("max_polls", 60))):
            if i:
                self.sleep(opts.get("poll_seconds", 5))
            blob = self.transport("GET", url, headers={**self._headers, "Accept": "audio/*"}, raw=True)
            if blob:
                return {"bytes": blob, "mime": MIME[fmt], "cost": None, "model": model}
        raise Retryable("timed out")
