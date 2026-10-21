"""Azure Speech Services adapter (TTS + Transcription).  Standard library only.

API shapes (verified against Azure Speech REST docs 2026-10-20):
  type = "azure_speech"
  capabilities = {"tts", "transcribe"}
  fields = ["api_key", "region"]
  TTS base URL per region: https://<region>.tts.speech.microsoft.com
  Transcription base URL per region: https://<region>.api.cognitive.microsoft.com
  Auth: Ocp-Apim-Subscription-Key header (API key) for both TTS and transcription

UNVERIFIED (assumed from docs, not live-tested):
  - Exact fast transcription endpoint path and response shape (docs reference /speechtotext/transcriptions:transcribe but exact path varies by API version)
  - Whether transcription supports word-level timestamps via REST (docs say chunk-level only)
  - Custom voice deployment endpoint format

list_models(): GET /tts/cognitiveservices/voices/list -> returns [{"id": voice.ShortName, "name": voice.DisplayName, "capability": "tts", "locale": voice.Locale, "gender": voice.Gender, "voice_type": voice.VoiceType, "style_list": voice.StyleList, "sample_rate": voice.SampleRateHertz}].
test(): GET /tts/cognitiveservices/voices/list (cheap call); returns {"ok": True, "message": "..."} on success, {"ok": False, "message": scrubbed_error} on failure. Never raises.
tts(model, text, voice_id, opts): POST /cognitiveservices/v1 with SSML body, headers: Ocp-Apim-Subscription-Key, Content-Type: application/ssml+xml, X-Microsoft-OutputFormat, User-Agent -> returns audio bytes. Response: {"bytes": audio_bytes, "mime": mime_from_format, "cost": None, "model": model}.
transcribe(model, audio_path, opts): POST /speechtotext/transcriptions:transcribe?api-version=2025-10-15 with multipart/form-data (file, definition JSON) -> returns {"transcript": ..., "words": [{"text": ..., "start": ..., "end": ...}]}. Note: fast transcription returns chunk-level timestamps, not word-level.
list_voices(): GET /tts/cognitiveservices/voices/list -> returns full voice objects from API.
"""
import json
import mimetypes
import os
import urllib.parse
from pathlib import Path

from aistudio.providers.base import Adapter, Retryable, AuthError, NotFound, Rejected, scrub


class AzureSpeechAdapter(Adapter):
    type = "azure_speech"
    capabilities = frozenset({"tts", "transcribe"})
    task_methods = frozenset({"tts", "transcribe"})
    # Base URLs are built from region; default_base_url not used directly

    def __init__(self, conn, transport=None):
        super().__init__(conn, transport)
        self.region = self.secret.get("region", "eastus")
        # TTS endpoint
        self.tts_base_url = f"https://{self.region}.tts.speech.microsoft.com"
        # Transcription endpoint (Speech to text REST API v3.2+)
        self.stt_base_url = f"https://{self.region}.api.cognitive.microsoft.com"

    def _tts_headers(self, output_format):
        key = self.secret.get("api_key")
        return {
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": output_format,
            "User-Agent": "AIStudio/1.0",
        }

    def _stt_headers(self):
        key = self.secret.get("api_key")
        return {
            "Ocp-Apim-Subscription-Key": key,
        }

    def _build_ssml(self, text, voice_id, opts=None):
        """Build SSML for TTS request."""
        opts = opts or {}
        # voice_id is the ShortName like "en-US-JennyNeural"
        # Extract locale from voice_id if possible, else default
        locale = opts.get("locale") or (voice_id.split("-")[0] + "-" + voice_id.split("-")[1] if "-" in voice_id else "en-US")
        gender = opts.get("gender", "Female")
        # Build SSML
        ssml = f"""<speak version='1.0' xml:lang='{locale}'><voice xml:lang='{locale}' xml:gender='{gender}' name='{voice_id}'>{text}</voice></speak>"""
        return ssml

    def _mime_from_format(self, output_format):
        """Convert Azure output format to MIME type."""
        if "mp3" in output_format:
            return "audio/mpeg"
        if "opus" in output_format:
            return "audio/opus"
        if "wav" in output_format or "riff" in output_format:
            return "audio/wav"
        if "alaw" in output_format:
            return "audio/basic"
        if "mulaw" in output_format:
            return "audio/basic"
        return "audio/mpeg"

    def list_models(self):
        """List available voices as models."""
        data = self._get_voices()
        out = []
        for v in data:
            short_name = v.get("ShortName", "")
            out.append({
                "id": short_name,
                "name": v.get("DisplayName", short_name),
                "capability": "tts",
                "locale": v.get("Locale", ""),
                "gender": v.get("Gender", ""),
                "voice_type": v.get("VoiceType", ""),
                "style_list": v.get("StyleList", []),
                "sample_rate": v.get("SampleRateHertz", 0),
            })
        return out

    def _get_voices(self):
        url = self.tts_base_url + "/tts/cognitiveservices/voices/list"
        headers = {"Ocp-Apim-Subscription-Key": self.secret.get("api_key")}
        return self.transport("GET", url, headers=headers)

    def test(self):
        """Check connectivity via voices list."""
        try:
            self._get_voices()
        except Exception as e:
            return {"ok": False, "message": scrub(e, self.secret)[:200]}
        return {"ok": True, "message": "Connected successfully"}

    def tts(self, model, text, voice_id, opts=None):
        opts = opts or {}
        output_format = opts.get("output_format", "riff-24khz-16bit-mono-pcm")
        ssml = self._build_ssml(text, voice_id, opts)
        url = self.tts_base_url + "/cognitiveservices/v1"
        headers = self._tts_headers(output_format)
        # Transport with raw body (SSML as bytes)
        resp = self.transport("POST", url, headers=headers, body=ssml.encode("utf-8"), raw=True)
        mime = self._mime_from_format(output_format)
        return {"bytes": resp, "mime": mime, "cost": None, "model": model}

    def transcribe(self, model, audio_path, opts=None):
        """Fast transcription via REST API."""
        opts = opts or {}
        p = Path(audio_path)
        mime = mimetypes.guess_type(p.name)[0] or "audio/wav"
        file_bytes = p.read_bytes()

        # Build multipart form data
        boundary = "----aiStudioBoundary" + os.urandom(8).hex()

        # Definition JSON for transcription parameters
        definition = {
            "locales": [opts.get("language_code", "en-US")] if opts.get("language_code") else ["en-US"],
            "profanityFilterMode": "Masked",
            "diarizationEnabled": opts.get("diarize", False),
            "wordLevelTimestampsEnabled": opts.get("word_timestamps", False),  # May not be supported in REST
        }
        definition_json = json.dumps(definition)

        body_parts = []
        # File part
        body_parts.append(f"--{boundary}")
        body_parts.append(f'Content-Disposition: form-data; name="audio"; filename="{p.name}"')
        body_parts.append(f"Content-Type: {mime}")
        body_parts.append("")
        body_parts.append(file_bytes.decode("latin-1"))
        # Definition part
        body_parts.append(f"--{boundary}")
        body_parts.append('Content-Disposition: form-data; name="definition"')
        body_parts.append("Content-Type: application/json")
        body_parts.append("")
        body_parts.append(definition_json)
        body_parts.append(f"--{boundary}--")
        body_parts.append("")

        body_str = "\r\n".join(body_parts)

        headers = dict(self._stt_headers())
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

        # Fast transcription endpoint (API version 2025-10-15)
        url = f"{self.stt_base_url}/speechtotext/transcriptions:transcribe?api-version=2025-10-15"

        resp = self.transport("POST", url, headers=headers, body=body_str)

        # Parse response - fast transcription returns combinedPhrases
        transcript = ""
        words = []
        if isinstance(resp, dict):
            # Combined phrases format
            for phrase in resp.get("combinedPhrases", []):
                transcript += phrase.get("text", "") + " "
            # Chunk-level timestamps (sentence/phrase segments)
            for phrase in resp.get("phrases", []):
                words.append({
                    "text": phrase.get("text", ""),
                    "start": phrase.get("offsetInTicks", 0) / 10_000_000,  # Convert ticks to seconds
                    "end": (phrase.get("offsetInTicks", 0) + phrase.get("durationInTicks", 0)) / 10_000_000,
                })
        return {"text": transcript.strip(), "words": words}

    def list_voices(self):
        return self._get_voices()

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
