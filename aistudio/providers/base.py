"""Provider adapter foundation: errors, the one HTTP transport, and the Adapter base class.  Standard library only.

An ADAPTER knows one API family (OpenAI, Anthropic, Google ...).  A CONNECTION (`conn`) is the user's configured provider:
    {"id": "my-openai", "type": "openai", "base_url": "https://api.openai.com/v1" (optional), "secret": {"api_key": "..."}}
The secret is passed in memory only; adapters never log it and never put it in an error message (see `scrub`).

TRANSPORT contract (all network access, injectable so tests never touch the network):
    transport(method, url, headers=None, body=None, raw=False, timeout=None) -> dict | list | bytes
      body is a JSON-able object (sent as application/json) ; raw=True returns bytes instead of parsed JSON.
      Raises (all subclasses of ProviderError): AuthError (401/403), NotFound (404), Rejected (other 4xx), Retryable (429, 5xx,
      timeouts, network errors).  Messages never contain header values.

ADAPTER interface (a method an adapter does not support raises Unsupported):
    list_models() -> [{"id","name","capability"}]              free call
    test() -> {"ok": bool, "message": str}                       free call, never raises
    chat(model, messages, opts=None) -> {"text","usage":{"input","output"},"cost":float|None,"model"}
    vision(model, prompt, images, opts=None) -> same shape as chat     (images = local file paths)
    image(model, prompt, refs=(), aspect_ratio="9:16", opts=None) -> {"bytes","usage":{},"cost":float|None,"model"}
    video_submit(model, req) -> {"job_id","model"}       req = {"prompt","seconds","resolution","aspect_ratio","audio","first_frame"(path|None)}
    video_poll(job) -> {"status":"pending"|"done"|"failed","error":str|None,"cost":float|None}      job = {"job_id","model"}
    video_download(job) -> bytes
`cost` is the provider-REPORTED dollar cost, or None when the provider does not report one (pricing.py then computes it).
"""
import base64
import json
import mimetypes
import os
import re
import urllib.error
import urllib.request
from pathlib import Path


class ProviderError(Exception):
    pass


class Retryable(ProviderError):
    """429, 5xx, timeout, network error, empty answer: worth retrying or trying the next model."""


class AuthError(ProviderError):
    """401/403 or no credit: the key is wrong, revoked or out of money."""


class NotFound(ProviderError):
    """404: the model or endpoint does not exist."""


class Rejected(ProviderError):
    """Other 4xx: the request was refused (bad parameters, safety block)."""


class Unsupported(ProviderError):
    """This adapter cannot do that capability."""


def classify_status(code, text=""):
    msg = f"HTTP {code}: {str(text)[:300]}"
    if code in (401, 402, 403):
        return AuthError(msg)
    if code == 404:
        return NotFound(msg)
    if code == 408 or code == 429 or code >= 500:
        return Retryable(msg)
    return Rejected(msg)


def scrub(text, secret=None):
    """Remove the secret values (and anything that looks like a bearer key) from a message."""
    text = str(text)
    for v in (secret or {}).values():
        if isinstance(v, str) and len(v) >= 6:
            text = text.replace(v, "***")
    return re.sub(r"(sk-[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{20,})", "***", text)


def default_transport(timeout=120, secret=None):
    def transport(method, url, headers=None, body=None, raw=False, timeout=timeout):
        if os.environ.get("AISTUDIO_NO_NETWORK") == "1":
            raise Retryable("network disabled by AISTUDIO_NO_NETWORK=1")
        hdrs = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, method=method, data=data, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                blob = r.read()
        except urllib.error.HTTPError as e:
            raise classify_status(e.code, scrub(e.read().decode(errors="replace"), secret)) from None
        except TimeoutError:
            raise Retryable("request timed out") from None
        except urllib.error.URLError as e:
            raise Retryable(f"network error: {scrub(e.reason, secret)}") from None
        if raw:
            return blob
        try:
            return json.loads(blob) if blob else {}
        except ValueError:
            raise Retryable("provider returned something that is not JSON") from None
    return transport


def data_url(path):
    p = Path(path)
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def b64_of(path):
    return base64.b64encode(Path(path).read_bytes()).decode()


def mime_of(path):
    return mimetypes.guess_type(Path(path).name)[0] or "image/png"


class Adapter:
    type = ""
    capabilities = frozenset()
    default_base_url = ""

    def __init__(self, conn, transport=None):
        self.conn = conn
        self.secret = conn.get("secret") or {}
        self.base_url = (conn.get("base_url") or self.default_base_url).rstrip("/")
        self.transport = transport or default_transport(secret=self.secret)

    def _unsupported(self, what):
        raise Unsupported(f"{self.type} cannot do {what}")

    def list_models(self):
        self._unsupported("list_models")

    def test(self):
        try:
            n = len(self.list_models())
            return {"ok": True, "message": f"Connected successfully ({n} models)"}
        except ProviderError as e:
            return {"ok": False, "message": scrub(e, self.secret)[:200]}

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
