"""Sarvam AI adapter (TTS via Bulbul, Transcription via Saaras).  Standard library only.

API shapes (verified against Sarvam AI docs 2026-10-20):
  type = "sarvam"
  capabilities = {"tts", "transcribe"}
  default_base_url = "https://api.sarvam.ai"
  Auth: api-subscription-key header

UNVERIFIED (assumed from docs, not live-tested):
  - Exact model IDs for list_models() (API doesn't have a models list endpoint; we return known models)
  - Whether TTS supports all listed language codes in practice
  - Transcription timestamps are chunk-level (sentence/phrase), not word-level

list_models(): Returns known models [{"id": "bulbul:v4-flash", "name": "Bulbul v4 Flash", "capability": "tts"}, {"id": "bulbul:v3", "name": "Bulbul v3", "capability": "tts"}, {"id": "saaras:v4", "name": "Saaras v4", "capability": "transcribe"}, {"id": "saaras:v3", "name": "Saaras v3", "capability": "transcribe"}].
test(): POST /text-to-speech with minimal payload; returns {"ok": True, "message": "..."} on success, {"ok": False, "message": scrubbed_error} on failure. Never raises.
tts(model, text, voice_id, opts): POST /text-to-speech with body {"text": text, "language_code": opts.get("language_code", "en-IN"), "speaker": voice_id, "model": model, "pace": opts.get("pace", 1.0), "pitch": opts.get("pitch"), "loudness": opts.get("loudness"), "speech_sample_rate": opts.get("speech_sample_rate", 22050), "output_audio_codec": opts.get("output_audio_codec", "wav"), "temperature": opts.get("temperature", 0.6), "enable_preprocessing": opts.get("enable_preprocessing", False)} -> returns base64 audios[0]. Response: {"bytes": decoded_audio, "mime": mime_from_codec, "cost": None, "model": model}.
transcribe(model, audio_path, opts): POST /speech-to-text multipart/form-data with file, model, language_code, with_timestamps -> returns {"transcript": ..., "language_code": ..., "timestamps": {"words": [...], "start_time_seconds": [...], "end_time_seconds": [...]}}. Response: {"text": transcript, "words": [{"text": w, "start": s, "end": e}]}.
list_voices(): Not directly available via API; returns known speakers for bulbul:v3 and bulbul:v4-flash with Tamil (ta-IN) support documented.
"""
import base64
import json
import mimetypes
import os
from pathlib import Path

from aistudio.providers.base import Adapter, Retryable, AuthError, NotFound, Rejected, scrub


class SarvamAdapter(Adapter):
    type = "sarvam"
    capabilities = frozenset({"tts", "transcribe"})
    default_base_url = "https://api.sarvam.ai"

    # Known speakers for bulbul:v3 (30+ voices) - subset listed here
    BULBUL_V3_SPEAKERS = [
        "shubh", "aditya", "ritu", "priya", "neha", "rahul", "pooja", "rohan", "simran",
        "kavya", "amit", "dev", "ishita", "shreya", "ratan", "varun", "manan", "sumit",
        "roopa", "kabir", "aayan", "ashutosh", "advait", "anand", "tanya", "tarun",
        "sunny", "mani", "gokul", "vijay", "shruti", "suhani", "mohit", "kavitha",
        "rehan", "soham", "rupali"
    ]

    # Known speakers for bulbul:v2 (legacy)
    BULBUL_V2_SPEAKERS = ["anushka", "manisha", "vidya", "arya", "abhilash", "karun", "hitesh"]

    # Supported language codes for TTS
    TTS_LANGUAGES = ["bn-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN", "ml-IN", "mr-IN", "od-IN", "pa-IN", "ta-IN", "te-IN"]

    # Supported language codes for transcription
    STT_LANGUAGES = ["unknown", "hi-IN", "bn-IN", "kn-IN", "ml-IN", "mr-IN", "od-IN", "pa-IN", "ta-IN", "te-IN", "en-IN", "gu-IN", "as-IN", "ur-IN", "ne-IN", "kok-IN", "ks-IN", "sd-IN", "sa-IN", "sat-IN", "mni-IN", "brx-IN", "mai-IN", "doi-IN"]

    def _headers(self, content_type="application/json"):
        key = self.secret.get("api_key")
        return {
            "api-subscription-key": key,
            "Content-Type": content_type,
        }

    def list_models(self):
        """Return known models since API doesn't have a models list endpoint."""
        return [
            {"id": "bulbul:v4-flash", "name": "Bulbul v4 Flash (200+ personas)", "capability": "tts"},
            {"id": "bulbul:v3", "name": "Bulbul v3 (30+ voices)", "capability": "tts"},
            {"id": "bulbul:v2", "name": "Bulbul v2 (legacy, pitch/loudness)", "capability": "tts"},
            {"id": "saaras:v4", "name": "Saaras v4 (latest STT)", "capability": "transcribe"},
            {"id": "saaras:v3", "name": "Saaras v3 (STT with modes)", "capability": "transcribe"},
        ]

    def test(self):
        """Check connectivity via a minimal TTS request."""
        try:
            # Minimal TTS request to test auth
            self._post_json("/text-to-speech", {
                "text": "test",
                "language_code": "en-IN",
                "speaker": "shubh",
                "model": "bulbul:v3",
            })
        except Exception as e:
            return {"ok": False, "message": scrub(e, self.secret)[:200]}
        return {"ok": True, "message": "Connected successfully"}

    def _post_json(self, path, body, raw=False):
        url = self.base_url + path
        return self.transport("POST", url, headers=self._headers(), body=body, raw=raw)

    def tts(self, model, text, voice_id, opts=None):
        opts = opts or {}
        # Determine model-specific defaults
        is_v2 = model == "bulbul:v2"
        body = {
            "text": text,
            "language_code": opts.get("language_code", "en-IN"),
            "speaker": voice_id,
            "model": model,
            "pace": opts.get("pace", 1.0),
            "speech_sample_rate": opts.get("speech_sample_rate", 22050),
            "output_audio_codec": opts.get("output_audio_codec", "wav"),
            "temperature": opts.get("temperature", 0.6) if not is_v2 else 0.6,
            "enable_preprocessing": opts.get("enable_preprocessing", False),
        }
        # v2-only params
        if is_v2:
            if opts.get("pitch") is not None:
                body["pitch"] = opts["pitch"]
            if opts.get("loudness") is not None:
                body["loudness"] = opts["loudness"]
        # v3/v4-flash params
        else:
            if opts.get("dict_id"):
                body["dict_id"] = opts["dict_id"]
        # Remove None values
        body = {k: v for k, v in body.items() if v is not None}

        resp = self._post_json("/text-to-speech", body)
        audios = resp.get("audios", [])
        if not audios:
            raise Retryable("no audio in response")
        audio_b64 = audios[0]
        audio_bytes = base64.b64decode(audio_b64)
        mime = self._mime_from_codec(opts.get("output_audio_codec", "wav"))
        return {"bytes": audio_bytes, "mime": mime, "cost": None, "model": model}

    def transcribe(self, model, audio_path, opts=None):
        opts = opts or {}
        p = Path(audio_path)
        mime = mimetypes.guess_type(p.name)[0] or "audio/wav"
        file_bytes = p.read_bytes()

        # Build multipart form data
        boundary = "----aiStudioBoundary" + os.urandom(8).hex()

        fields = {
            "model": model,
        }
        if opts.get("language_code"):
            fields["language_code"] = opts["language_code"]
        if opts.get("mode"):  # Only for saaras:v3
            fields["mode"] = opts["mode"]
        if opts.get("with_timestamps"):
            fields["with_timestamps"] = "true"
        if opts.get("input_audio_codec"):
            fields["input_audio_codec"] = opts["input_audio_codec"]
        if opts.get("keyterms"):
            import json as json_lib
            fields["keyterms"] = json_lib.dumps(opts["keyterms"])

        body_parts = []
        for name, value in fields.items():
            body_parts.append(f"--{boundary}")
            body_parts.append(f'Content-Disposition: form-data; name="{name}"')
            body_parts.append("")
            body_parts.append(str(value))
        # File part
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

        url = self.base_url + "/speech-to-text"
        resp = self.transport("POST", url, headers=headers, body=body_str)

        # Parse response
        transcript = resp.get("transcript", "")
        words = []
        timestamps = resp.get("timestamps")
        if timestamps:
            ts_words = timestamps.get("words", [])
            start_times = timestamps.get("start_time_seconds", [])
            end_times = timestamps.get("end_time_seconds", [])
            for i, w in enumerate(ts_words):
                words.append({
                    "text": w,
                    "start": start_times[i] if i < len(start_times) else 0.0,
                    "end": end_times[i] if i < len(end_times) else 0.0,
                })
        return {"text": transcript, "words": words}

    def list_voices(self):
        """Return known speakers for each model. Tamil (ta-IN) supported."""
        voices = []
        # bulbul:v3 speakers
        for spk in self.BULBUL_V3_SPEAKERS:
            voices.append({
                "speaker": spk,
                "model": "bulbul:v3",
                "languages": self.TTS_LANGUAGES,
            })
        # bulbul:v2 speakers
        for spk in self.BULBUL_V2_SPEAKERS:
            voices.append({
                "speaker": spk,
                "model": "bulbul:v2",
                "languages": self.TTS_LANGUAGES,
            })
        # Note: bulbul:v4-flash has 200+ personas, not listed here
        # User should refer to Sarvam Voices guide for full list
        voices.append({
            "speaker": "shubh_enhi_ads (and 200+ personas)",
            "model": "bulbul:v4-flash",
            "languages": self.TTS_LANGUAGES,
            "note": "See Sarvam Voices guide for full persona catalog"
        })
        return voices

    def _mime_from_codec(self, codec):
        mapping = {
            "wav": "audio/wav",
            "mp3": "audio/mpeg",
            "aac": "audio/aac",
            "flac": "audio/flac",
            "linear16": "audio/wav",
            "mulaw": "audio/basic",
            "alaw": "audio/basic",
            "opus": "audio/opus",
        }
        return mapping.get(codec, "audio/wav")

    # Unsupported capabilities
    def chat(self, model, messages, opts=None):
        self._unsupported("chat")

    def vision(self, model, prompt, images, opts=None):
        self._unsupported("vision")

    def image(self, model, prompt, refs=(), aspect_ratio="9:16", opts=None):
        self._unsupported("image generation")

    def video_submit(self, model, req):
        self._unsupported("video generation")

    def video_poll(self, job):
        self._unsupported("video generation")

    def video_download(self, job):
        self._unsupported("video generation")

    def sfx(self, model, prompt, seconds, opts=None):
        self._unsupported("sfx")

    def music(self, model, prompt, seconds, opts=None):
        self._unsupported("music")

    def voice_clone(self, model, audio_path, opts=None):
        self._unsupported("voice_clone")