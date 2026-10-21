"""Tavus (tavus.io) - talking head video generation and lip sync.  Standard library only.

API shapes (verified against Tavus API OpenAPI spec 2026-10-21):
  type = "tavus"
  capabilities = {"lipsync", "video"}
  default_base_url = "https://tavusapi.com"
  Auth: header {"x-api-key": <api_key>}

Endpoints used:
  POST /v2/videos                 -> {"video_id": "...", "status": "queued", ...}
  GET  /v2/videos/{video_id}      -> {"video_id": "...", "status": "queued"|"generating"|"ready"|"error", "download_url": "...", "hosted_url": "..."}

UNVERIFIED (not live-tested):
  - The deprecated /v2/lipsync endpoint is marked deprecated in the spec.
  - We implement lip sync via the video generation endpoint using audio_url + replica_id (face).
  - Exact status values for all edge cases.

Video generation (POST /v2/videos) accepts:
  - replica_id (face ID) - required
  - script (text) OR audio_url (publicly accessible audio file) - one required
  - optional: video_name, background_url, background_source_url, callback_url, fast, transparent_background, watermark_image_url, properties

Note: The legacy "lipsync" endpoint (/v2/lipsync) is deprecated. Lip sync is achieved by
generating a video with a face (replica_id) and an audio_url.
"""
import json

from aistudio.providers.base import Adapter, AuthError, Rejected, Retryable, scrub


class TavusAdapter(Adapter):
    type = "tavus"
    capabilities = frozenset({"lipsync", "video"})
    default_base_url = "https://tavusapi.com"

    def __init__(self, conn, transport=None):
        super().__init__(conn, transport)
        self._key = self.secret.get("api_key")

    def _headers(self):
        if not self._key:
            return {}
        return {"x-api-key": self._key}

    def _require_key(self):
        if not self._key:
            raise AuthError("no API key for Tavus")
        return self._key

    def list_models(self):
        """Tavus uses faces (replicas) and voices rather than models. Return known model aliases."""
        return [
            {"id": "phoenix-4.5", "name": "Phoenix 4.5 (Face Model)", "capability": "video"},
            {"id": "phoenix-4", "name": "Phoenix 4 (Face Model)", "capability": "video"},
            {"id": "phoenix-3", "name": "Phoenix 3 (Legacy Face Model)", "capability": "video"},
        ]

    def test(self):
        try:
            self._require_key()
            self.transport("GET", f"{self.base_url}/v2/faces", headers=self._headers())
            return {"ok": True, "message": "Connected successfully"}
        except Exception as e:
            return {"ok": False, "message": scrub(e, self.secret)[:200]}

    # --------------------------- lip sync ----------------------------------

    def lipsync_submit(self, model, video_path, audio_path, opts=None):
        """
        Submit a lip sync job via video generation with audio_url.
        Note: Tavus doesn't have a direct lip sync endpoint (deprecated).
        We generate a video using a face (replica_id) and the provided audio.
        
        model: the face/replica ID to use (or "phoenix-4.5" etc. - caller must provide a valid face_id)
        video_path: NOT USED for Tavus lip sync (the face is pre-trained). 
                    Kept for API compatibility; should be a face_id or replica_id.
        audio_path: URL to the audio file (must be publicly accessible .wav or .mp3)
        opts: optional dict with "video_name", "background_url", "background_source_url"
        """
        opts = opts or {}
        self._require_key()

        # For Tavus, the "model" parameter is actually the face_id/replica_id
        # The video_path parameter is expected to be the face_id (since Tavus uses pre-trained faces)
        face_id = video_path  # In our API, video_path carries the face_id
        audio_url = audio_path  # audio_path carries the audio URL

        if not face_id:
            raise Rejected("face_id (replica_id) is required for Tavus lip sync")
        if not audio_url:
            raise Rejected("audio_url is required for Tavus lip sync")

        body = {
            "replica_id": face_id,
            "audio_url": audio_url,
        }
        if opts.get("video_name"):
            body["video_name"] = opts["video_name"]
        if opts.get("background_url"):
            body["background_url"] = opts["background_url"]
        if opts.get("background_source_url"):
            body["background_source_url"] = opts["background_source_url"]
        if opts.get("fast") is not None:
            body["fast"] = opts["fast"]
        if opts.get("transparent_background") is not None:
            body["transparent_background"] = opts["transparent_background"]
        if opts.get("watermark_image_url"):
            body["watermark_image_url"] = opts["watermark_image_url"]
        if opts.get("properties"):
            body["properties"] = opts["properties"]

        resp = self.transport(
            "POST",
            f"{self.base_url}/v2/videos",
            headers={**self._headers(), "Content-Type": "application/json"},
            body=body
        )
        data = resp if isinstance(resp, dict) else json.loads(resp or "{}")
        video_id = data.get("video_id")
        if not video_id:
            raise Retryable("Tavus did not return a video ID")
        return {"job_id": video_id, "model": model}

    def lipsync_poll(self, job):
        job_id = job["job_id"]
        resp = self.transport("GET", f"{self.base_url}/v2/videos/{job_id}", headers=self._headers())
        data = resp if isinstance(resp, dict) else json.loads(resp or "{}")
        status = data.get("status", "")
        if status in ("queued", "generating"):
            return {"status": "pending", "error": None, "cost": None}
        if status == "ready":
            return {"status": "done", "error": None, "cost": None}
        if status in ("error", "deleted"):
            return {"status": "failed", "error": data.get("error_details") or "generation failed", "cost": None}
        return {"status": "pending", "error": None, "cost": None}

    def lipsync_download(self, job):
        job_id = job["job_id"]
        resp = self.transport("GET", f"{self.base_url}/v2/videos/{job_id}", headers=self._headers())
        data = resp if isinstance(resp, dict) else json.loads(resp or "{}")
        if data.get("status") != "ready":
            raise Retryable("not finished")
        url = data.get("download_url") or data.get("hosted_url")
        if not url:
            raise Retryable("no download URL")
        return self.transport("GET", url, headers={}, raw=True)

    # --------------------------- video ----------------------------------

    def video_submit(self, model, req):
        """
        Submit a video generation job (text-to-video or audio-to-video with a face).
        req: {"prompt": str (script), "face_id": str (replica_id), "audio_url": str|None,
              "video_name": str|None, "background_url": str|None, ...}
        """
        self._require_key()

        face_id = req.get("face_id") or req.get("replica_id")
        if not face_id:
            raise Rejected("face_id (replica_id) is required")

        body = {"replica_id": face_id}

        # Either script or audio_url
        if req.get("audio_url"):
            body["audio_url"] = req["audio_url"]
        elif req.get("prompt"):
            body["script"] = req["prompt"]
        else:
            raise Rejected("Either audio_url or script (prompt) is required")

        # Optional fields
        for key in ("video_name", "background_url", "background_source_url", "callback_url",
                    "fast", "transparent_background", "watermark_image_url"):
            if req.get(key) is not None:
                body[key] = req[key]
        if req.get("properties"):
            body["properties"] = req["properties"]

        resp = self.transport(
            "POST",
            f"{self.base_url}/v2/videos",
            headers={**self._headers(), "Content-Type": "application/json"},
            body=body
        )
        data = resp if isinstance(resp, dict) else json.loads(resp or "{}")
        video_id = data.get("video_id")
        if not video_id:
            raise Retryable("Tavus did not return a video ID")
        return {"job_id": video_id, "model": model}

    def video_poll(self, job):
        return self.lipsync_poll(job)  # Same polling logic

    def video_download(self, job):
        return self.lipsync_download(job)  # Same download logic