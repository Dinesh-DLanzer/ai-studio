"""Hedra (hedra.com) - talking avatar / lip sync and video generation.  Standard library only.

API shapes (verified against Hedra v3 API OpenAPI spec 2026-10-21):
  type = "hedra"
  capabilities = {"lipsync", "video"}
  default_base_url = "https://api.hedra.com"
  Auth: header {"Authorization": "Key <key_id>:<secret>"} (also accepts Bearer <key_id>:<secret>).

UNVERIFIED (not live-tested):
  - Exact model IDs for lip sync (assumed "veed-fabric-10" based on spec).
  - Exact job status values and response shapes for lip sync models.
  - The exact error codes; only HTTP status is used for classification.

Submit pattern: POST /v3/models/{model} with {"input": {...}, "webhook": null} ->
  202 {"job_id": "job_...", "model": "...", "status": "PENDING", ...}.
Poll: GET /v3/jobs/{job_id} -> {"job_id": "...", "status": "PENDING"|"PROCESSING"|"COMPLETED"|"FAILED", "outputs": [...], "error": {...}}.
Download: when status == "COMPLETED", outputs[0].url is a presigned download URL (fetch without auth).

Lip sync model (veed-fabric-10) inputs: {"prompt": str, "aspect_ratio": "16:9"|"9:16"|"4:3"|"3:4"|"1:1",
  "resolution": "480p"|"720p", "start_image": {"source": "url"|"asset", "url": "..."|"asset_id": "..."},
  "audio": {"source": "url"|"asset", "url": "..."|"asset_id": "..."}}
Video generation models (e.g., veo-3, wan-3-0, etc.) have various inputs; we expose a generic submit
where the caller provides the model-specific input dict.
"""
import json
import mimetypes
import os
import uuid
from pathlib import Path

from aistudio.providers.base import Adapter, AuthError, Rejected, Retryable, scrub


def _multipart(fields, files):
    """Build a multipart/form-data body.  fields: {name: str}; files: {name: (filename, bytes, content-type)}."""
    boundary = "----aistudio" + uuid.uuid4().hex
    out = bytearray()
    for name, value in fields.items():
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += f"{value}\r\n".encode()
    for name, (filename, content, content_type) in files.items():
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        out += f"Content-Type: {content_type}\r\n\r\n".encode()
        out += content
        out += b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


class HedraAdapter(Adapter):
    type = "hedra"
    capabilities = frozenset({"lipsync", "video"})
    default_base_url = "https://api.hedra.com"

    def __init__(self, conn, transport=None):
        super().__init__(conn, transport)
        # secret has api_key (key_id:secret)
        self._key = self.secret.get("api_key")

    def _headers(self):
        if not self._key:
            return {}
        return {"Authorization": f"Key {self._key}"}

    def _require_key(self):
        if not self._key:
            raise AuthError("no API key for Hedra")
        return self._key

    def list_models(self):
        """List available models from Hedra."""
        resp = self.transport("GET", f"{self.base_url}/v3/models", headers=self._headers())
        models = resp if isinstance(resp, list) else (resp or {}).get("data", [])
        out = []
        for m in models:
            if not isinstance(m, dict):
                continue
            mid = m.get("slug") or m.get("id")
            if not mid:
                continue
            # Map modality to capability
            cap = "video"
            if m.get("modality") == "video":
                cap = "video"
            elif m.get("modality") == "image":
                cap = "image"
            elif m.get("modality") == "audio":
                cap = "tts"
            out.append({"id": mid, "name": m.get("name") or mid, "capability": cap})
        return out

    def test(self):
        try:
            self._require_key()
            self.transport("GET", f"{self.base_url}/v3/models", headers=self._headers())
            return {"ok": True, "message": "Connected successfully"}
        except Exception as e:
            return {"ok": False, "message": scrub(e, self.secret)[:200]}

    def _file_field(self, path):
        p = Path(str(path)).expanduser()
        if not p.exists():
            raise Rejected(f"file not found: {p}")
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        return p.name, p.read_bytes(), ctype

    def _upload_file(self, path):
        """Upload a file to Hedra's /v3/files and return the file URL."""
        self._require_key()
        name, content, ctype = self._file_field(path)
        body, content_type = _multipart({}, {"file": (name, content, ctype)})
        resp = self.transport(
            "POST",
            f"{self.base_url}/v3/files",
            headers={**self._headers(), "Content-Type": content_type},
            body=body
        )
        data = resp if isinstance(resp, dict) else json.loads(resp or "{}")
        url = data.get("url")
        if not url:
            raise Retryable("Hedra did not return a file URL")
        return url

    def _submit_job(self, model, input_data):
        """Submit a job to a model."""
        self._require_key()
        body = {"input": input_data, "webhook": None}
        resp = self.transport(
            "POST",
            f"{self.base_url}/v3/models/{model}",
            headers={**self._headers(), "Content-Type": "application/json"},
            body=body
        )
        data = resp if isinstance(resp, dict) else json.loads(resp or "{}")
        job_id = data.get("job_id")
        if not job_id:
            raise Retryable("Hedra did not return a job ID")
        return {"job_id": job_id, "model": model}

    def _poll_job(self, job_id):
        """Poll a job status."""
        self._require_key()
        resp = self.transport("GET", f"{self.base_url}/v3/jobs/{job_id}", headers=self._headers())
        return resp if isinstance(resp, dict) else json.loads(resp or "{}")

    def _download_output(self, output_url):
        """Download the output file (no auth needed for presigned URLs)."""
        return self.transport("GET", output_url, headers={}, raw=True)

    # --------------------------- lip sync ----------------------------------

    def lipsync_submit(self, model, video_path, audio_path, opts=None):
        """
        Submit a lip sync job.
        model: the Hedra model ID (e.g., "veed-fabric-10")
        video_path: path to the source video/image (start frame)
        audio_path: path to the driving audio
        opts: optional dict with "aspect_ratio", "resolution", "prompt"
        """
        opts = opts or {}
        self._require_key()

        # Upload files to get URLs
        video_url = self._upload_file(video_path)
        audio_url = self._upload_file(audio_path)

        input_data = {
            "prompt": opts.get("prompt", "A person talking"),
            "aspect_ratio": opts.get("aspect_ratio", "16:9"),
            "resolution": opts.get("resolution", "720p"),
            "start_image": {"source": "url", "url": video_url},
            "audio": {"source": "url", "url": audio_url},
        }
        return self._submit_job(model, input_data)

    def lipsync_poll(self, job):
        job_id = job["job_id"]
        data = self._poll_job(job_id)
        status = data.get("status", "")
        if status in ("PENDING", "PROCESSING", "QUEUED"):
            return {"status": "pending", "error": None, "cost": None}
        if status == "COMPLETED":
            return {"status": "done", "error": None, "cost": None}
        if status == "FAILED":
            error = data.get("error", {})
            msg = error.get("message") if isinstance(error, dict) else str(error)
            return {"status": "failed", "error": msg or "generation failed", "cost": None}
        return {"status": "pending", "error": None, "cost": None}

    def lipsync_download(self, job):
        job_id = job["job_id"]
        data = self._poll_job(job_id)
        if data.get("status") != "COMPLETED":
            raise Retryable("not finished")
        outputs = data.get("outputs", [])
        if not outputs:
            raise Retryable("no outputs available")
        url = outputs[0].get("url")
        if not url:
            raise Retryable("no download URL")
        return self._download_output(url)

    # --------------------------- video ----------------------------------

    def video_submit(self, model, req):
        """
        Submit a video generation job.
        req: {"prompt": str, "seconds": int, "resolution": str, "aspect_ratio": str,
              "first_frame": path|None, "audio": bool}
        For Hedra, we use a generic model submit with model-specific inputs.
        The caller must provide the correct input structure for the model in req.get("hedra_input").
        """
        self._require_key()
        hedra_input = req.get("hedra_input")
        if not hedra_input:
            # Build a basic input for common video models
            hedra_input = {
                "prompt": req.get("prompt", ""),
            }
            # Add optional fields
            if req.get("aspect_ratio"):
                hedra_input["aspect_ratio"] = req["aspect_ratio"]
            if req.get("resolution"):
                hedra_input["resolution"] = req["resolution"]
            if req.get("seconds"):
                hedra_input["duration_ms"] = int(req["seconds"] * 1000)
            if req.get("first_frame"):
                # Upload the first frame
                frame_url = self._upload_file(req["first_frame"])
                hedra_input["start_image"] = {"source": "url", "url": frame_url}
        return self._submit_job(model, hedra_input)

    def video_poll(self, job):
        return self.lipsync_poll(job)  # Same polling logic

    def video_download(self, job):
        return self.lipsync_download(job)  # Same download logic