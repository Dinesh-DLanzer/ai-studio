"""sync.so (sync. labs): lip sync - the lips in a video follow an audio track.  Standard library only.

NOTE: the shapes below come from sync.so's public OpenAPI specification (https://sync.so/docs/openapi.json,
read on 2026-10-20) and must be re-checked against the live docs before release.
Subclass of aistudio.providers.base.Adapter (read its docstring first).
  type = "sync" ; capabilities = {"lipsync"} ; default_base_url = "https://api.sync.so"
  The secret has ONE field: self.secret["api_key"].  Every request carries the header {"x-api-key": <api_key>}
  (the specification's security scheme is an apiKey in the header named "x-api-key").

Endpoints used here (all verified in the OpenAPI file):
  GET  /v2/models                     -> [{"id","name","type","version"}]
  POST /v2/generate                   -> a generation.  The local files are sent as multipart/form-data
                                          (the "Create Generation with Files" form): the file fields are
                                          "video" and "audio" (at most one of each), "model" is required and
                                          "options" is a JSON STRING.  Answer: 201 with the generation object.
  GET  /v2/generate/{id}              -> the generation object: {"id","status","model","input","createdAt",
                                          "outputUrl","error","errorCode"}.  status is one of
                                          PENDING | PROCESSING | COMPLETED | FAILED | REJECTED.
  GET  /v2/generations/{id}/download  -> text/plain: an UNQUOTED url of the finished file.  Fetch that url
                                          separately and WITHOUT the api key.

lipsync_submit(model, video_path, audio_path, opts) -> {"job_id","model"}
  opts: {"sync_mode": "cut_off" (default) | "bounce" | "loop" | "silence" | "remap", "output_file_name": "..."}
  The generation is created with the two files in one multipart request, so nothing has to be public.
lipsync_poll(job) -> {"status":"pending"|"done"|"failed","error":str|None,"cost":None}
lipsync_download(job) -> bytes

UNVERIFIED: the "options" field is only in the specification, not in a live call (the plan's tests use a
fake transport), and the "sync_mode" default here is cut_off (the API's own default is bounce): cut_off trims
the video to the length of the audio, which is what a shot with a voice line needs.  The exact error codes
are not used; only the HTTP status decides the error class.
"""
import json
import mimetypes
import uuid
from pathlib import Path

from aistudio.providers.base import Adapter, AuthError, Rejected, Retryable, scrub

DEFAULT_SYNC_MODE = "cut_off"
SYNC_MODES = ("bounce", "loop", "cut_off", "silence", "remap")


def multipart(fields, files):
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


class SyncAdapter(Adapter):
    type = "sync"
    capabilities = frozenset({"lipsync"})
    default_base_url = "https://api.sync.so"

    # ---------------------------------------------------------------- helpers
    @property
    def _headers(self):
        return {"x-api-key": self.secret.get("api_key") or ""}

    def _key(self):
        key = str(self.secret.get("api_key") or "").strip()
        if not key:
            raise AuthError("no API key for sync.so")
        return key

    def _get(self, path):
        return self.transport("GET", self.base_url + path, headers=self._headers)

    def _generation(self, job_id):
        body = self._get("/v2/generate/" + str(job_id))
        return body if isinstance(body, dict) else json.loads(body or "{}")

    @staticmethod
    def _file_field(path):
        p = Path(str(path)).expanduser()
        if not p.exists():
            raise Rejected(f"file not found: {p}")
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        return p.name, p.read_bytes(), ctype

    # ---------------------------------------------------------------- calls
    def list_models(self):
        body = self._get("/v2/models")
        models = body if isinstance(body, list) else (body or {}).get("data") or []
        out = []
        for m in models:
            if not isinstance(m, dict):
                continue
            mid = m.get("id") or m.get("name")
            if not mid:
                continue
            out.append({"id": mid, "name": m.get("name") or mid, "capability": "lipsync"})
        return out

    def test(self):
        try:
            self._key()
            self._get("/v2/models")
            return {"ok": True, "message": "Connected successfully"}
        except Exception as e:
            return {"ok": False, "message": scrub(e, self.secret)[:200]}

    def lipsync_submit(self, model, video_path, audio_path, opts=None):
        opts = opts or {}
        self._key()
        video = self._file_field(video_path)
        audio = self._file_field(audio_path)
        mode = str(opts.get("sync_mode") or DEFAULT_SYNC_MODE)
        if mode not in SYNC_MODES:
            raise Rejected(f"sync_mode must be one of {', '.join(SYNC_MODES)}")
        fields = {"model": str(model), "options": json.dumps({"sync_mode": mode})}
        if opts.get("output_file_name"):
            fields["outputFileName"] = str(opts["output_file_name"])
        body, content_type = multipart(fields, {"video": video, "audio": audio})
        resp = self.transport("POST", self.base_url + "/v2/generate",
                              headers={**self._headers, "Content-Type": content_type},
                              body=body)
        doc = resp if isinstance(resp, dict) else json.loads(resp or "{}")
        job_id = doc.get("id")
        if not job_id:
            raise Retryable("sync.so did not return a generation id")
        return {"job_id": job_id, "model": model}

    def lipsync_poll(self, job):
        doc = self._generation(job["job_id"])
        status = str(doc.get("status") or "").upper()
        if status in ("PENDING", "PROCESSING"):
            return {"status": "pending", "error": None, "cost": None}
        if status == "COMPLETED":
            return {"status": "done", "error": None, "cost": None}
        if status in ("FAILED", "REJECTED"):
            return {"status": "failed", "error": doc.get("error") or doc.get("errorCode") or "generation failed", "cost": None}
        return {"status": "pending", "error": None, "cost": None}

    def lipsync_download(self, job):
        doc = self._generation(job["job_id"])
        if str(doc.get("status") or "").upper() != "COMPLETED":
            raise Retryable("not finished")
        blob = self.transport("GET", self.base_url + "/v2/generations/" + str(job["job_id"]) + "/download",
                              headers=self._headers, raw=True)
        url = blob.decode("utf-8", "replace") if isinstance(blob, bytes) else str(blob or "")
        url = url.strip().strip('"').strip()
        if not url.startswith("http"):
            raise Retryable("sync.so did not return a download url")
        return self.transport("GET", url, headers={}, raw=True)
