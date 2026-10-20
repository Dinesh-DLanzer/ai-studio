"""fal.ai adapter: one queue-based gateway to many hosted models.  Standard library only.

API shapes (verified against the fal documentation on 2026-10-20,
https://fal.ai/docs/inference-api/queue and https://fal.ai/docs/platform-apis/v1/models):
  type = "fal"
  capabilities = {"music", "sfx", "lipsync", "tts", "image", "video"}
  default_base_url = "https://queue.fal.run"   (the queue API)
  platform_base_url = "https://api.fal.ai/v1"   (the platform API: the model search)
  Header on EVERY request: {"Authorization": "Key " + api_key}

Queue API (the model id IS the endpoint path):
  POST {queue}/{model}      body = the input of the model (JSON, the fields differ per model)
                             -> {"request_id", "response_url", "status_url", "cancel_url",
                                 "queue_position", "status"}
  GET  {status_url}         -> {"status": "IN_QUEUE" | "IN_PROGRESS" | "COMPLETED", "queue_position",
                                 "logs", "metrics", "error", "error_type"}
  GET  {response_url}       -> the output of the model (the shape is model specific)
  The request URLs use only the owner and the app ("fal-ai/flux"), never the endpoint path
  ("fal-ai/flux/schnell/requests/..." answers 405), so they are taken from the submit answer.
  A failed or cancelled request also has the status COMPLETED; it carries an "error".

Platform API:
  GET {platform}/models?limit=&q=&category=&endpoint_id=&sort=&expand=
      -> {"models": [{"endpoint_id", "metadata": {"display_name", "category", "tags", ...}}],
          "has_more": bool, "next_cursor": id | null}

The result of a model is model specific: an image model returns {"images": [{"url": ...}]}, a video
model returns {"video": {"url": ...}} and an audio or speech model returns {"audio": {"url": ...}} or
an "audio_url".

UNVERIFIED:
  - the price of a request: the queue does not report a cost, so cost is always None.
  - GET {platform}/models accepts requests without a key, so the health check proves that the
    platform API answers, not that the key is good.  A wrong key is only seen on the first call.
  - the exact media key of a result is model specific; download() looks in the documented keys
    ("audio", "video", "image", "images", "audio_url", "video_url", "image_url", "output", "file").
  - local files are never uploaded: fal models take URLs, so a caller that needs a file must give
    fal a URL (or upload it with the fal storage API, which this adapter does not use).
"""
import time
import urllib.parse

from aistudio.providers.base import Adapter, AuthError, Rejected, Retryable, scrub

PLATFORM_BASE_URL = "https://api.fal.ai/v1"

# The keys of a result that hold media, in the order they are looked at.
MEDIA_KEYS = ("audio", "video", "image", "images", "audio_url", "video_url", "image_url",
              "output", "file", "files")

# The categories of the platform model search that the adapter lists.
CATEGORIES = ("text-to-audio", "text-to-speech", "text-to-image", "text-to-video")

LIPSYNC_TAGS = ("lipsync", "lip-sync")
SFX_TAGS = ("sfx", "sound", "sound-effects", "effects")
SPEECH_TAGS = ("speech", "tts", "text-to-speech", "voice", "voice-clone", "clone-voice")
MUSIC_TAGS = ("music",)
VIDEO_CATEGORIES = ("text-to-video", "image-to-video", "video-to-video")
IMAGE_CATEGORIES = ("text-to-image", "image-to-image")


class FalAdapter(Adapter):
    type = "fal"
    capabilities = frozenset({"music", "sfx", "lipsync", "tts", "image", "video"})
    default_base_url = "https://queue.fal.run"

    def __init__(self, conn, transport=None, sleep=time.sleep):
        super().__init__(conn, transport)
        self.sleep = sleep
        self.platform_base = (conn.get("platform_base_url") or PLATFORM_BASE_URL).rstrip("/")

    # ---------------------------------------------------------------- helpers
    @property
    def _headers(self):
        return {"Authorization": "Key " + (self.secret.get("api_key") or "")}

    def _key(self):
        key = str(self.secret.get("api_key") or "").strip()
        if not key:
            raise AuthError("no API key for fal")
        return key

    @staticmethod
    def _model_id(model):
        parts = [p for p in str(model or "").strip("/").split("/") if p]
        if len(parts) < 2:
            raise Rejected("a fal model id looks like owner/app (for example fal-ai/flux/dev)")
        return "/".join(parts)

    def _request_base(self, model):
        """The owner and the app of a model: the request URLs never carry the endpoint path."""
        return "/".join(self._model_id(model).split("/")[:2])

    def _status_url(self, job):
        url = job.get("status_url")
        if url:
            return url
        base = self._request_base(job.get("model"))
        return f"{self.base_url}/{base}/requests/{job['job_id']}/status"

    def _response_url(self, job):
        url = job.get("response_url")
        if url:
            return url
        base = self._request_base(job.get("model"))
        return f"{self.base_url}/{base}/requests/{job['job_id']}"

    @staticmethod
    def _media_url(result):
        """The first media url of a model specific result."""
        if isinstance(result, str):
            return result if result.startswith("http") else None
        if isinstance(result, list):
            for item in result:
                url = FalAdapter._media_url(item)
                if url:
                    return url
            return None
        if isinstance(result, dict):
            for key in MEDIA_KEYS:
                if key in result:
                    url = FalAdapter._media_url(result[key])
                    if url:
                        return url
            url = result.get("url")
            return url if isinstance(url, str) and url.startswith("http") else None
        return None

    @staticmethod
    def _capability_of(entry):
        """The capability of a model of the platform search."""
        meta = entry.get("metadata") or {}
        category = str(meta.get("category") or "").lower()
        tags = [str(t).lower() for t in (meta.get("tags") or [])]
        eid = str(entry.get("endpoint_id") or "").lower()
        if any(t in tags for t in LIPSYNC_TAGS) or "lipsync" in eid or "lip-sync" in eid:
            return "lipsync"
        if category == "text-to-speech":
            return "tts"
        if category in ("text-to-audio", "audio-to-audio"):
            if any(t in tags for t in SFX_TAGS):
                return "sfx"
            if any(t in tags for t in SPEECH_TAGS):
                return "tts"
            return "music"
        if category in VIDEO_CATEGORIES:
            return "video"
        if category in IMAGE_CATEGORIES:
            return "image"
        return None

    def _search(self, **params):
        url = self.platform_base + "/models"
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean, doseq=True)
        doc = self.transport("GET", url, headers=self._headers)
        doc = doc if isinstance(doc, dict) else {}
        models = doc.get("models")
        return models if isinstance(models, list) else []

    # ---------------------------------------------------------------- calls
    def list_models(self):
        """The models of the platform search, mapped to the capabilities of this adapter."""
        self._key()
        seen, out = set(), []
        entries = []
        for category in CATEGORIES:
            entries += self._search(category=category, limit=50, status="active")
        entries += self._search(q="lipsync", limit=50, status="active")
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            eid = entry.get("endpoint_id")
            cap = self._capability_of(entry)
            if not eid or not cap or (eid, cap) in seen:
                continue
            seen.add((eid, cap))
            meta = entry.get("metadata") or {}
            out.append({"id": eid, "name": meta.get("display_name") or eid, "capability": cap})
        return out

    def test(self):
        try:
            self._key()
            self._search(limit=1)
            return {"ok": True, "message": "Connected successfully"}
        except Exception as e:
            return {"ok": False, "message": scrub(e, self.secret)[:200]}

    def submit(self, model, input=None, opts=None):
        """Put a request on the queue.  Returns {"job_id", "model", "status_url", "response_url"}."""
        opts = opts or {}
        self._key()
        model = self._model_id(model)
        body = dict(input or {})
        headers = {**self._headers, "Content-Type": "application/json"}
        if opts.get("webhook_url"):
            headers["fal_webhook"] = str(opts["webhook_url"])
        doc = self.transport("POST", f"{self.base_url}/{model}", headers=headers, body=body)
        doc = doc if isinstance(doc, dict) else {}
        job_id = doc.get("request_id")
        if not job_id:
            raise Retryable("fal did not return a request id")
        return {"job_id": job_id, "model": model,
                "status_url": doc.get("status_url"), "response_url": doc.get("response_url")}

    def poll(self, job):
        """The state of a queued request: {"status": "pending" | "done" | "failed", ...}."""
        doc = self.transport("GET", self._status_url(job), headers=self._headers)
        doc = doc if isinstance(doc, dict) else {}
        status = str(doc.get("status") or "").upper()
        if status == "COMPLETED":
            if doc.get("error"):
                return {"status": "failed", "error": str(doc.get("error")), "cost": None}
            return {"status": "done", "error": None, "cost": None}
        return {"status": "pending", "error": None, "cost": None}

    def result(self, job):
        """The output of a finished request (the shape is model specific)."""
        doc = self.transport("GET", self._response_url(job), headers=self._headers)
        return doc if isinstance(doc, dict) else {"value": doc}

    def download(self, job):
        """The bytes of the media of a finished request."""
        url = self._media_url(self.result(job))
        if not url:
            raise Retryable("fal returned no media url")
        return self.transport("GET", url, headers={}, raw=True)

    def generate(self, model, input=None, opts=None):
        """Submit, wait and download in one call.  Returns {"bytes", "usage", "cost", "model"}."""
        opts = opts or {}
        job = self.submit(model, input, opts)
        for i in range(int(opts.get("max_polls", 60))):
            if i:
                self.sleep(opts.get("poll_seconds", 2))
            state = self.poll(job)
            if state["status"] == "failed":
                raise Rejected(state.get("error") or "generation failed")
            if state["status"] == "done":
                return {"bytes": self.download(job), "usage": {}, "cost": None, "model": job["model"]}
        raise Retryable("timed out")

    # ---------------------------------------------------------------- image and video
    def image(self, model, prompt, refs=(), aspect_ratio="9:16", opts=None):
        opts = opts or {}
        inputs = {"prompt": prompt, "aspect_ratio": aspect_ratio}
        extra = opts.get("input_extra")
        if isinstance(extra, dict):
            inputs.update(extra)
        return self.generate(model, inputs, opts)

    def video_submit(self, model, req):
        req = req or {}
        inputs = {"prompt": req.get("prompt")}
        if req.get("seconds"):
            inputs["duration"] = int(req["seconds"])
        if req.get("aspect_ratio"):
            inputs["aspect_ratio"] = req["aspect_ratio"]
        if req.get("resolution"):
            inputs["resolution"] = req["resolution"]
        extra = req.get("input_extra")
        if isinstance(extra, dict):
            inputs.update(extra)
        job = self.submit(model, inputs)
        return {"job_id": job["job_id"], "model": job["model"], "status_url": job["status_url"],
                "response_url": job["response_url"]}

    def video_poll(self, job):
        return self.poll(job)

    def video_download(self, job):
        doc = self.transport("GET", self._response_url(job), headers=self._headers)
        doc = doc if isinstance(doc, dict) else {}
        if str(doc.get("status") or "").upper() not in ("COMPLETED", ""):
            raise Retryable("not finished")
        url = self._media_url(doc)
        if not url:
            raise Retryable("not finished")
        return self.transport("GET", url, headers={}, raw=True)
