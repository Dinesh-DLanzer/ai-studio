"""Google Cloud Text-to-Speech adapter (TTS).  Standard library only.

API shapes (verified against Google Cloud TTS docs 2026-10-20):
  type = "google_cloud_tts"
  capabilities = {"tts"}
  default_base_url = "https://texttospeech.googleapis.com"
  Auth: API key passed as query parameter ?key=<api_key> (REST API key auth)

UNVERIFIED (assumed from docs, not live-tested):
  - Exact voice name format for voice_id parameter in tts()
  - Audio encoding defaults and exact byte response handling
  - Whether API key auth works for all endpoints (some require OAuth)

list_models(): GET /v1/voices -> returns [{"id": voice.name, "name": voice.name, "capability": "tts", "language_codes": voice.languageCodes, "ssml_gender": voice.ssmlGender, "sample_rate": voice.naturalSampleRateHertz}].
test(): GET /v1/voices (cheap call); returns {"ok": True, "message": "..."} on success, {"ok": False, "message": scrubbed_error} on failure. Never raises.
tts(model, text, voice_id, opts): POST /v1/text:synthesize with body {"input": {"text": text}, "voice": {"name": voice_id}, "audioConfig": {"audioEncoding": opts.get("audio_encoding", "MP3"), "speakingRate": opts.get("speaking_rate", 1.0), "pitch": opts.get("pitch", 0.0), "volumeGainDb": opts.get("volume_gain_db", 0.0), "sampleRateHertz": opts.get("sample_rate_hertz", 24000)}} -> returns base64 audioContent. Response: {"bytes": decoded_audio, "mime": mime_type, "cost": None, "model": model}.
list_voices(): GET /v1/voices -> returns full voice objects from API.
"""
import base64
import json
import urllib.parse
from pathlib import Path

from aistudio.providers.base import Adapter, Retryable, AuthError, NotFound, Rejected, scrub, classify_status


class GoogleCloudTTSAdapter(Adapter):
    type = "google_cloud_tts"
    capabilities = frozenset({"tts"})
    task_methods = frozenset({"tts"})
    default_base_url = "https://texttospeech.googleapis.com"

    def _headers(self):
        # Google Cloud REST API uses API key as query param, not header
        return {"Content-Type": "application/json"}

    def _url_with_key(self, path, params=None):
        """Build URL with API key as query parameter."""
        url = self.base_url + path
        query_params = dict(params or {})
        key = self.secret.get("api_key")
        if key:
            query_params["key"] = key
        if query_params:
            url += "?" + urllib.parse.urlencode(query_params)
        return url

    def _post_json(self, path, body, params=None, raw=False):
        url = self._url_with_key(path, params)
        return self.transport("POST", url, headers=self._headers(), body=body, raw=raw)

    def _get(self, path, params=None):
        url = self._url_with_key(path, params)
        return self.transport("GET", url, headers=self._headers())

    def list_models(self):
        """List available voices as models."""
        data = self._get("/v1/voices")
        out = []
        for v in data.get("voices", []):
            name = v.get("name", "")
            out.append({
                "id": name,
                "name": name,
                "capability": "tts",
                "language_codes": v.get("languageCodes", []),
                "ssml_gender": v.get("ssmlGender", ""),
                "sample_rate": v.get("naturalSampleRateHertz", 0),
            })
        return out

    def test(self):
        """Check connectivity via voices list."""
        try:
            self._get("/v1/voices", params={"languageCode": "en-US"})
        except Exception as e:
            return {"ok": False, "message": scrub(e, self.secret)[:200]}
        return {"ok": True, "message": "Connected successfully"}

    def tts(self, model, text, voice_id, opts=None):
        opts = opts or {}
        # Build request body matching Google Cloud TTS API
        body = {
            "input": {"text": text},
            "voice": {"name": voice_id},
            "audioConfig": {
                "audioEncoding": opts.get("audio_encoding", "MP3"),
                "speakingRate": opts.get("speaking_rate", 1.0),
                "pitch": opts.get("pitch", 0.0),
                "volumeGainDb": opts.get("volume_gain_db", 0.0),
            }
        }
        if opts.get("sample_rate_hertz"):
            body["audioConfig"]["sampleRateHertz"] = opts["sample_rate_hertz"]
        # Advanced voice options (optional)
        if opts.get("low_latency_journey_synthesis") is not None:
            body["advancedVoiceOptions"] = {
                "lowLatencyJourneySynthesis": opts["low_latency_journey_synthesis"]
            }

        resp = self._post_json("/v1/text:synthesize", body)
        audio_content = resp.get("audioContent", "")
        if not audio_content:
            raise Retryable("no audio content in response")
        audio_bytes = base64.b64decode(audio_content)
        mime = self._mime_from_encoding(opts.get("audio_encoding", "MP3"))
        return {"bytes": audio_bytes, "mime": mime, "cost": None, "model": model}

    def list_voices(self):
        data = self._get("/v1/voices")
        return data.get("voices", [])

    def _mime_from_encoding(self, encoding):
        mapping = {
            "MP3": "audio/mpeg",
            "LINEAR16": "audio/wav",
            "OGG_OPUS": "audio/opus",
            "MULAW": "audio/basic",
            "ALAW": "audio/basic",
        }
        return mapping.get(encoding, "audio/mpeg")

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

    def transcribe(self, model, audio_path, opts=None):
        self._unsupported("transcribe")

    def sfx(self, model, prompt, seconds, opts=None):
        self._unsupported("sfx")

    def music(self, model, prompt, seconds, opts=None):
        self._unsupported("music")

    def voice_clone(self, model, audio_path, opts=None):
        self._unsupported("voice_clone")
