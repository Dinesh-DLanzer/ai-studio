"""Cartesia adapter (text-to-speech and voice cloning).  Standard library only.

API shapes (verified against the Cartesia OpenAPI reference on 2026-10-20, API version 2026-08-14,
https://docs.cartesia.ai/api-reference):
  type = "cartesia"
  capabilities = {"tts", "voice_clone"}
  default_base_url = "https://api.cartesia.ai"
  Headers on EVERY request: {"Authorization": "Bearer " + api_key, "Cartesia-Version": "2026-08-14"}
  (the version header is required by the API; today it is an enum with that single value)

Endpoints used here:
  POST /tts/bytes      JSON body: {"model_id", "transcript", "voice", "output_format"} - all four are
                        required - plus the optional "language" or "locale", "accent", "normalization",
                        "pronunciation_dict_id" and "generation_config" {"volume", "speed", "emotion"}.
                        Answer: 200 with the audio bytes.
  POST /voices/clone   multipart/form-data: "clip" (the audio file, max 16 MB), "name" and "language"
                        (both required), plus the optional "tagline" (max 32 characters), "description",
                        "accent", "base_voice_id" and "access" ("private" | "public").
                        Answer: 200 with the voice object: {"id", "name", "language", "access", ...}.
  GET  /voices         ?limit=&starting_after=&ending_before=&q=&is_owner=&gender=&language=
                        Answer: {"data": [voice, ...], "has_more": bool, "next_page": id | null}

The TTS model ids in the API schema: sonic-3.6 (the default), sonic-3.5, sonic-3 and sonic-latest.
The output format is an object: {"container": "mp3", "sample_rate": 44100, "bit_rate": 128000} or
{"container": "wav", "encoding": "pcm_s16le", "sample_rate": 44100} or {"container": "raw", ...}.
The voice is either the voice id as a string or {"id": ...}.

UNVERIFIED:
  - the price of a request: the API does not report one, so cost is always None.
  - the "Cartesia-Version" header: the version is a required enum with a single value today.  A
    newer API version may add values; this adapter sends the one the docs list.
  - a voice clone needs the speaker's recorded consent.  The consent record is plan 16's job; this
    adapter only uploads the clip it is given.
"""
import json
import mimetypes
import urllib.parse
import uuid
from pathlib import Path

from aistudio.providers.base import Adapter, AuthError, Rejected, Retryable, scrub

API_VERSION = "2026-08-14"
TTS_PATH = "/tts/bytes"
CLONE_PATH = "/voices/clone"
VOICES_PATH = "/voices"

# The TTS models in the API schema.
MODELS = (("sonic-3.6", "Sonic 3.6"),
          ("sonic-3.5", "Sonic 3.5"),
          ("sonic-3", "Sonic 3"),
          ("sonic-latest", "Sonic (latest)"))

MIME = {"mp3": "audio/mpeg", "wav": "audio/wav", "raw": "audio/L16"}


def multipart(fields, files=None):
    """Build a multipart/form-data body.  fields: {name: str}; files: {name: (filename, bytes, type)}."""
    boundary = "----aistudio" + uuid.uuid4().hex
    out = bytearray()
    for name, value in fields.items():
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += f"{value}\r\n".encode()
    for name, (filename, content, content_type) in (files or {}).items():
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        out += f"Content-Type: {content_type}\r\n\r\n".encode()
        out += content
        out += b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


class CartesiaAdapter(Adapter):
    type = "cartesia"
    capabilities = frozenset({"tts", "voice_clone"})
    task_methods = frozenset({"tts"})
    default_base_url = "https://api.cartesia.ai"

    # ---------------------------------------------------------------- helpers
    @property
    def _headers(self):
        return {"Authorization": "Bearer " + (self.secret.get("api_key") or ""),
                "Cartesia-Version": API_VERSION}

    def _key(self):
        key = str(self.secret.get("api_key") or "").strip()
        if not key:
            raise AuthError("no API key for Cartesia")
        return key

    def _get(self, path, params=None):
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        return self.transport("GET", url, headers=self._headers)

    # ---------------------------------------------------------------- calls
    def list_models(self):
        """Cartesia has no model list endpoint: the TTS model ids come from the API schema."""
        return [{"id": mid, "name": name, "capability": "tts"} for mid, name in MODELS]

    def test(self):
        try:
            self._key()
            self._get(VOICES_PATH, {"limit": 1})
            return {"ok": True, "message": "Connected successfully"}
        except Exception as e:
            return {"ok": False, "message": scrub(e, self.secret)[:200]}

    def tts(self, model, text, voice_id, opts=None):
        """Text to speech.  Returns {"bytes", "mime", "cost", "model"}."""
        opts = opts or {}
        self._key()
        fmt = opts.get("output_format") or {"container": "mp3", "sample_rate": 44100, "bit_rate": 128000}
        if isinstance(fmt, str):
            fmt = {"container": fmt}
        if not isinstance(fmt, dict) or "container" not in fmt:
            raise Rejected("output_format must be an object with a container (mp3, wav or raw)")
        voice = opts.get("voice") or voice_id
        if isinstance(voice, dict):
            if not voice.get("id"):
                raise Rejected("a voice object needs an id")
        elif not voice:
            raise Rejected("a voice id is required")
        body = {"model_id": str(model or "sonic-3.6"), "transcript": text, "voice": voice,
                "output_format": fmt}
        for k in ("language", "locale", "accent", "normalization", "pronunciation_dict_id"):
            if opts.get(k) is not None:
                body[k] = opts[k]
        gc = opts.get("generation_config")
        if isinstance(gc, dict):
            body["generation_config"] = gc
        blob = self.transport("POST", self.base_url + TTS_PATH, headers=self._headers, body=body, raw=True)
        return {"bytes": blob, "mime": MIME.get(str(fmt.get("container")).lower(), "audio/mpeg"),
                "cost": None, "model": body["model_id"]}

    def voice_clone(self, name, clip_path, language, opts=None):
        """Clone a voice from an audio clip.  Returns {"voice_id", "name", "language"}."""
        opts = opts or {}
        self._key()
        if not name:
            raise Rejected("a name is required for the cloned voice")
        if not language:
            raise Rejected("a language is required for the cloned voice")
        p = Path(str(clip_path)).expanduser()
        if not p.exists():
            raise Rejected(f"file not found: {p}")
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        fields = {"name": str(name), "language": str(language)}
        for k in ("tagline", "description", "accent", "base_voice_id", "access"):
            if opts.get(k) is not None:
                fields[k] = str(opts[k])
        body, content_type = multipart(fields, {"clip": (p.name, p.read_bytes(), ctype)})
        doc = self.transport("POST", self.base_url + CLONE_PATH,
                             headers={**self._headers, "Content-Type": content_type}, body=body)
        doc = doc if isinstance(doc, dict) else json.loads(doc or "{}")
        voice_id = doc.get("id")
        if not voice_id:
            raise Retryable("Cartesia did not return a voice id")
        return {"voice_id": voice_id, "name": doc.get("name") or fields["name"],
                "language": doc.get("language") or fields["language"]}

    def list_voices(self, opts=None):
        """The voices of the account and of the public library: [{"id", "name", ...}]."""
        opts = opts or {}
        doc = self._get(VOICES_PATH, {"limit": opts.get("limit", 50), "q": opts.get("q"),
                                      "language": opts.get("language"), "is_owner": opts.get("is_owner")})
        doc = doc if isinstance(doc, dict) else json.loads(doc or "{}")
        voices = doc.get("data")
        return voices if isinstance(voices, list) else []
