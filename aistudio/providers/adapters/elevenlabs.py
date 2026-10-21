"""ElevenLabs adapter (TTS, SFX, music, voice clone, transcription via Scribe).  Standard library only.

API shapes (verified against ElevenLabs docs 2026-10-20):
  type = "elevenlabs"
  capabilities = {"tts", "sfx", "music", "voice_clone", "transcribe"}
  default_base_url = "https://api.elevenlabs.io"
  Header on EVERY request: {"xi-api-key": <api_key>}

UNVERIFIED (assumed from docs, not live-tested):
  - Exact SFX and music model IDs (eleven_text_to_sound_v2, music_v1, music_v2, music_v2_5)
  - TTS output_format defaults and exact byte response handling
  - Transcription response shape word list details

list_models(): GET /v1/models -> returns [{"id": model_id, "name": name, "capability": "tts"|"sfx"|"music"|"transcribe"}] (capability inferred from can_do_text_to_speech etc.)
test(): GET /v1/user (user info) or fallback to list voices; returns {"ok": True, "message": "..."} on success, {"ok": False, "message": scrubbed_error} on failure. Never raises.
tts(model, text, voice_id, opts): POST /v1/text-to-speech/{voice_id}?output_format=... with body {"text", "model_id", "voice_settings"...} -> returns audio bytes. Response: {"bytes", "mime", "cost": None, "model"}.
sfx(model, prompt, seconds, opts): POST /v1/sound-generation?output_format=... with body {"text": prompt, "duration_seconds": seconds, "model_id": model} -> returns audio bytes. Same result shape.
music(model, prompt, seconds, opts): POST /v1/music?output_format=... with body {"prompt": prompt, "music_length_ms": seconds*1000, "model_id": model} -> returns audio bytes. Same result shape.
transcribe(model, audio_path, opts): POST /v1/speech-to-text (multipart) with model_id, file, timestamps_granularity="word" -> returns {"text": "...", "words": [{"text", "start", "end", "speaker_id"}]}.
list_voices(): GET /v2/voices -> returns [{"voice_id", "name", "category", "labels", "preview_url", ...}].
"""
import json
import mimetypes
import os
import urllib.parse
from pathlib import Path

from aistudio.providers.base import Adapter, Rejected, Retryable, AuthError, NotFound, scrub


class ElevenLabsAdapter(Adapter):
    type = "elevenlabs"
    capabilities = frozenset({"tts", "sfx", "music", "voice_clone", "transcribe"})
    default_base_url = "https://api.elevenlabs.io"

    def _headers(self):
        key = self.secret.get("api_key")
        return {"xi-api-key": key} if key else {}

    def _get(self, path, params=None, raw=False):
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return self.transport("GET", url, headers=self._headers(), raw=raw)

    def _post_json(self, path, body, params=None, raw=False):
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return self.transport("POST", url, headers=self._headers(), body=body, raw=raw)

    def _post_multipart(self, path, fields, files, params=None, raw=False):
        """Send multipart/form-data. fields: dict of form fields. files: dict of name -> (filename, bytes, mime)."""
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        # Build multipart body
        boundary = "----aiStudioBoundary" + os.urandom(8).hex()
        body_parts = []
        for name, value in fields.items():
            body_parts.append(f"--{boundary}")
            body_parts.append(f'Content-Disposition: form-data; name="{name}"')
            body_parts.append("")
            body_parts.append(str(value))
        for name, (filename, file_bytes, mime) in files.items():
            body_parts.append(f"--{boundary}")
            body_parts.append(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"')
            body_parts.append(f"Content-Type: {mime}")
            body_parts.append("")
            body_parts.append(file_bytes.decode("latin-1"))  # binary data as latin-1 string
        body_parts.append(f"--{boundary}--")
        body_parts.append("")
        body_str = "\r\n".join(body_parts)
        headers = dict(self._headers())
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        return self.transport("POST", url, headers=headers, body=body_str, raw=raw)

    def list_models(self):
        data = self._get("/v1/models")
        out = []
        for m in data:
            caps = []
            if m.get("can_do_text_to_speech"):
                caps.append("tts")
            if m.get("can_do_voice_conversion"):
                caps.append("voice_clone")
            # SFX and music models are separate; we infer from model_id
            mid = m.get("model_id", "")
            if "sound" in mid.lower() or "sfx" in mid.lower():
                caps.append("sfx")
            if mid.startswith("music_"):
                caps.append("music")
            if "scribe" in mid.lower():
                caps.append("transcribe")
            cap = caps[0] if caps else "tts"
            out.append({"id": mid, "name": m.get("name") or mid, "capability": cap})
        return out

    def test(self):
        """Check connectivity via /v1/user (user info) or list voices as fallback."""
        try:
            self._get("/v1/user")
        except Exception as e:
            try:
                # Fallback: list voices (cheap call)
                self._get("/v2/voices", params={"page_size": 1})
            except Exception as e2:
                return {"ok": False, "message": scrub(e2, self.secret)[:200]}
        return {"ok": True, "message": "Connected successfully"}

    def tts(self, model, text, voice_id, opts=None):
        opts = opts or {}
        params = {"output_format": opts.get("output_format", "mp3_44100_128")}
        if opts.get("enable_logging") is not None:
            params["enable_logging"] = str(opts["enable_logging"]).lower()
        body = {
            "text": text,
            "model_id": model,
        }
        # Voice settings (optional)
        vs = opts.get("voice_settings")
        if isinstance(vs, dict):
            body["voice_settings"] = vs
        # Optional extra params
        for k in ("language_code", "seed", "previous_text", "next_text", "previous_request_ids", "next_request_ids",
                  "use_pvc_as_ivc", "apply_text_normalization", "apply_language_text_normalization", "audio_effects"):
            if k in opts:
                body[k] = opts[k]
        resp = self._post_json(f"/v1/text-to-speech/{voice_id}", body, params=params, raw=True)
        mime = opts.get("mime") or self._mime_from_format(params["output_format"])
        return {"bytes": resp, "mime": mime, "cost": None, "model": model}

    def sfx(self, model, prompt, seconds, opts=None):
        opts = opts or {}
        params = {"output_format": opts.get("output_format", "mp3_44100_128")}
        if opts.get("enable_logging") is not None:
            params["enable_logging"] = str(opts["enable_logging"]).lower()
        body = {
            "text": prompt,
            "model_id": model,
        }
        if seconds is not None:
            body["duration_seconds"] = float(seconds)
        if opts.get("loop") is not None:
            body["loop"] = bool(opts["loop"])
        if opts.get("prompt_influence") is not None:
            body["prompt_influence"] = float(opts["prompt_influence"])
        resp = self._post_json("/v1/sound-generation", body, params=params, raw=True)
        mime = opts.get("mime") or self._mime_from_format(params["output_format"])
        return {"bytes": resp, "mime": mime, "cost": None, "model": model}

    def music(self, model, prompt, seconds, opts=None):
        opts = opts or {}
        params = {"output_format": opts.get("output_format", "auto")}
        if opts.get("enable_logging") is not None:
            params["enable_logging"] = str(opts["enable_logging"]).lower()
        body = {
            "prompt": prompt,
            "model_id": model,
        }
        if seconds is not None:
            body["music_length_ms"] = int(seconds * 1000)
        # Optional fields
        for k in ("composition_plan", "seed", "force_instrumental", "finetune_id",
                  "respect_sections_durations", "store_for_inpainting", "sign_with_c2pa"):
            if k in opts:
                body[k] = opts[k]
        resp = self._post_json("/v1/music", body, params=params, raw=True)
        mime = opts.get("mime") or self._mime_from_format(params["output_format"])
        return {"bytes": resp, "mime": mime, "cost": None, "model": model}

    def transcribe(self, model, audio_path, opts=None):
        opts = opts or {}
        # Read the audio file
        p = Path(audio_path)
        mime = mimetypes.guess_type(p.name)[0] or "audio/mpeg"
        file_bytes = p.read_bytes()
        # Build multipart form
        fields = {
            "model_id": model,
        }
        if opts.get("language_code"):
            fields["language_code"] = opts["language_code"]
        if opts.get("timestamps_granularity"):
            fields["timestamps_granularity"] = opts["timestamps_granularity"]
        else:
            fields["timestamps_granularity"] = "word"  # default to word-level timestamps
        if opts.get("diarize") is not None:
            fields["diarize"] = str(opts["diarize"]).lower()
        if opts.get("num_speakers"):
            fields["num_speakers"] = str(opts["num_speakers"])
        if opts.get("tag_audio_events") is not None:
            fields["tag_audio_events"] = str(opts["tag_audio_events"]).lower()
        if opts.get("no_verbatim") is not None:
            fields["no_verbatim"] = str(opts["no_verbatim"]).lower()
        if opts.get("entity_detection"):
            fields["entity_detection"] = opts["entity_detection"]
        if opts.get("transcript_edit"):
            fields["transcript_edit"] = opts["transcript_edit"]
        if opts.get("temperature") is not None:
            fields["temperature"] = str(opts["temperature"])
        if opts.get("seed") is not None:
            fields["seed"] = str(opts["seed"])
        if opts.get("file_format"):
            fields["file_format"] = opts["file_format"]
        # Note: We use a simple approach to multipart; the base transport handles JSON only.
        # For multipart we need to build it manually.
        files = {"file": (p.name, file_bytes, mime)}
        # Query params
        params = {}
        if opts.get("enable_logging") is not None:
            params["enable_logging"] = str(opts["enable_logging"]).lower()
        # Send via transport with multipart content type
        # Since base transport doesn't support multipart, we use a custom call
        # We'll use urllib directly via the transport's underlying mechanism
        # Simplest: just post with raw body and proper Content-Type header
        url = self.base_url + "/v1/speech-to-text"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        boundary = "----aiStudioBoundary" + os.urandom(8).hex()
        body_parts = []
        for name, value in fields.items():
            body_parts.append(f"--{boundary}")
            body_parts.append(f'Content-Disposition: form-data; name="{name}"')
            body_parts.append("")
            body_parts.append(str(value))
        body_parts.append(f"--{boundary}")
        body_parts.append(f'Content-Disposition: form-data; name="file"; filename="{p.name}"')
        body_parts.append(f"Content-Type: {mime}")
        body_parts.append("")
        body_parts.append(file_bytes.decode("latin-1"))
        body_parts.append(f"--{boundary}--")
        body_parts.append("")
        body_str = "\r\n".join(body_parts)
        headers = dict(self._headers())
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        resp = self.transport("POST", url, headers=headers, body=body_str)
        # Parse response
        text = resp.get("text", "")
        words = []
        for w in resp.get("words", []):
            words.append({
                "text": w.get("text", ""),
                "start": w.get("start", 0.0),
                "end": w.get("end", 0.0),
                "speaker_id": w.get("speaker_id"),
            })
        return {"text": text, "words": words}

    def list_voices(self):
        data = self._get("/v2/voices")
        voices = data.get("voices", [])
        return voices

    def _mime_from_format(self, fmt):
        """Convert output_format to MIME type."""
        if fmt.startswith("mp3"):
            return "audio/mpeg"
        if fmt.startswith("wav"):
            return "audio/wav"
        if fmt.startswith("pcm"):
            return "audio/pcm"
        if fmt.startswith("opus"):
            return "audio/opus"
        if fmt.startswith("ulaw") or fmt.startswith("alaw"):
            return "audio/basic"
        return "audio/mpeg"