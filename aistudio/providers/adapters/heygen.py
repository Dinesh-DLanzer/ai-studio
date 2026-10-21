"""HeyGen (heygen.com) - avatar video generation and lip sync.  Standard library only.

API shapes (verified against HeyGen External API OpenAPI spec 2026-10-21):
  type = "heygen"
  capabilities = {"lipsync", "video"}
  default_base_url = "https://api.heygen.com"
  Auth: header {"x-api-key": <api_key>}

Endpoints used:
  POST /v3/lipsyncs                 -> {"data": {"lipsync_id": "..."}}
  GET  /v3/lipsyncs/{lipsync_id}    -> {"data": {"id": "...", "status": "pending"|"running"|"completed"|"failed", "video_url": "...", "failure_message": "..."}}
  POST /v3/videos                   -> {"data": {"video_id": "...", "status": "waiting"}}
  GET  /v3/videos/{video_id}        -> {"data": {"id": "...", "status": "pending"|"processing"|"completed"|"failed", "video_url": "...", "error_details": "..."}}

UNVERIFIED (not live-tested):
  - Exact status values for all edge cases.
  - The exact error codes; only HTTP status is used for classification.

Video generation (POST /v3/videos) accepts:
  - avatar_id (HeyGen avatar ID) OR image_url OR image_asset_id
  - script + voice_id (for TTS) OR audio_url OR audio_asset_id
  - optional: title, background, etc.
"""
import json
import mimetypes
from pathlib import Path

from aistudio.providers.base import Adapter, AuthError, Rejected, Retryable, scrub


class HeyGenAdapter(Adapter):
    type = "heygen"
    capabilities = frozenset({"lipsync", "video"})
    task_methods = frozenset({"lipsync"})
    default_base_url = "https://api.heygen.com"

    def __init__(self, conn, transport=None):
        super().__init__(conn, transport)
        self._key = self.secret.get("api_key")

    def _headers(self):
        if not self._key:
            return {}
        return {"x-api-key": self._key}

    def _require_key(self):
        if not self._key:
            raise AuthError("no API key for HeyGen")
        return self._key

    def list_models(self):
        """HeyGen doesn't have a traditional model list; return known avatar/video models."""
        return [
            {"id": "avatar-v3", "name": "HeyGen Avatar III", "capability": "video"},
            {"id": "avatar-v4", "name": "HeyGen Avatar IV", "capability": "video"},
            {"id": "avatar-v5", "name": "HeyGen Avatar V", "capability": "video"},
            {"id": "lipsync-speed", "name": "Lip Sync Speed", "capability": "lipsync"},
            {"id": "lipsync-precision", "name": "Lip Sync Precision", "capability": "lipsync"},
        ]

    def test(self):
        try:
            self._require_key()
            self.transport("GET", f"{self.base_url}/v3/users/me", headers=self._headers())
            return {"ok": True, "message": "Connected successfully"}
        except Exception as e:
            return {"ok": False, "message": scrub(e, self.secret)[:200]}

    # --------------------------- lip sync ----------------------------------

    def lipsync_submit(self, model, video_path, audio_path, opts=None):
        """
        Submit a lip sync job.
        model: "lipsync-speed" or "lipsync-precision" (or other lipsync model ID)
        video_path: path to the source video (URL or local file path)
        audio_path: path to the driving audio (URL or local file path)
        opts: optional dict with "title"
        """
        opts = opts or {}
        self._require_key()

        # HeyGen accepts video/audio as either URL or asset_id.
        # For local files, we'd need to upload to assets first.
        # For simplicity, we assume the caller provides URLs or asset_ids.
        # If local paths are given, we treat them as URLs (user must host them).
        video_input = self._to_input(video_path)
        audio_input = self._to_input(audio_path)

        body = {
            "video": video_input,
            "audio": audio_input,
        }
        if opts.get("title"):
            body["title"] = opts["title"]

        resp = self.transport(
            "POST",
            f"{self.base_url}/v3/lipsyncs",
            headers={**self._headers(), "Content-Type": "application/json"},
            body=body
        )
        data = resp if isinstance(resp, dict) else json.loads(resp or "{}")
        lipsync_id = data.get("data", {}).get("lipsync_id")
        if not lipsync_id:
            raise Retryable("HeyGen did not return a lipsync ID")
        return {"job_id": lipsync_id, "model": model}

    def _to_input(self, path_or_url):
        """Convert a path or URL to HeyGen's input format."""
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            return {"type": "url", "url": path_or_url}
        # Assume it's an asset_id if it looks like one, otherwise treat as URL
        if path_or_url.startswith("asset_"):
            return {"type": "asset_id", "asset_id": path_or_url}
        # Default to URL (user must host the file)
        return {"type": "url", "url": path_or_url}

    def lipsync_poll(self, job):
        job_id = job["job_id"]
        resp = self.transport("GET", f"{self.base_url}/v3/lipsyncs/{job_id}", headers=self._headers())
        data = (resp if isinstance(resp, dict) else json.loads(resp or "{}")).get("data", {})
        status = data.get("status", "")
        if status in ("pending", "running"):
            return {"status": "pending", "error": None, "cost": None}
        if status == "completed":
            return {"status": "done", "error": None, "cost": None}
        if status == "failed":
            return {"status": "failed", "error": data.get("failure_message") or "lipsync failed", "cost": None}
        return {"status": "pending", "error": None, "cost": None}

    def lipsync_download(self, job):
        job_id = job["job_id"]
        resp = self.transport("GET", f"{self.base_url}/v3/lipsyncs/{job_id}", headers=self._headers())
        data = (resp if isinstance(resp, dict) else json.loads(resp or "{}")).get("data", {})
        if data.get("status") != "completed":
            raise Retryable("not finished")
        url = data.get("video_url")
        if not url:
            raise Retryable("no download URL")
        return self.transport("GET", url, headers={}, raw=True)

    # --------------------------- video ----------------------------------

    def video_submit(self, model, req):
        """
        Submit an avatar video generation job.
        req: {"prompt": str (script), "seconds": int, "resolution": str, "aspect_ratio": str,
              "avatar_id": str|None, "image_url": str|None, "voice_id": str|None,
              "audio_url": str|None, "title": str|None}
        """
        self._require_key()

        # Build request body
        body = {}

        # Visual source (mutually exclusive)
        if req.get("avatar_id"):
            body["avatar_id"] = req["avatar_id"]
        elif req.get("image_url"):
            body["image_url"] = req["image_url"]
        elif req.get("image_asset_id"):
            body["image_asset_id"] = req["image_asset_id"]
        else:
            raise Rejected("Exactly one visual source required: avatar_id, image_url, or image_asset_id")

        # Audio source (mutually exclusive)
        if req.get("audio_url"):
            body["audio_url"] = req["audio_url"]
        elif req.get("audio_asset_id"):
            body["audio_asset_id"] = req["audio_asset_id"]
        elif req.get("prompt"):  # script for TTS
            body["script"] = req["prompt"]
            if req.get("voice_id"):
                body["voice_id"] = req["voice_id"]
        else:
            raise Rejected("Either audio_url/audio_asset_id or script (prompt) with voice_id is required")

        # Optional fields
        if req.get("title"):
            body["title"] = req["title"]
        if req.get("background"):
            body["background"] = req["background"]

        resp = self.transport(
            "POST",
            f"{self.base_url}/v3/videos",
            headers={**self._headers(), "Content-Type": "application/json"},
            body=body
        )
        data = resp if isinstance(resp, dict) else json.loads(resp or "{}")
        video_id = data.get("data", {}).get("video_id")
        if not video_id:
            raise Retryable("HeyGen did not return a video ID")
        return {"job_id": video_id, "model": model}

    def video_poll(self, job):
        job_id = job["job_id"]
        resp = self.transport("GET", f"{self.base_url}/v3/videos/{job_id}", headers=self._headers())
        data = (resp if isinstance(resp, dict) else json.loads(resp or "{}")).get("data", {})
        status = data.get("status", "")
        if status in ("pending", "processing", "waiting"):
            return {"status": "pending", "error": None, "cost": None}
        if status == "completed":
            return {"status": "done", "error": None, "cost": None}
        if status == "failed":
            return {"status": "failed", "error": data.get("error_details") or "generation failed", "cost": None}
        return {"status": "pending", "error": None, "cost": None}

    def video_download(self, job):
        job_id = job["job_id"]
        resp = self.transport("GET", f"{self.base_url}/v3/videos/{job_id}", headers=self._headers())
        data = (resp if isinstance(resp, dict) else json.loads(resp or "{}")).get("data", {})
        if data.get("status") != "completed":
            raise Retryable("not finished")
        url = data.get("video_url")
        if not url:
            raise Retryable("no download URL")
        return self.transport("GET", url, headers={}, raw=True)
