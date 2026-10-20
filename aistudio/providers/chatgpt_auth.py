"""ChatGPT subscription sign-in (OAuth 2.0 PKCE, the same flow the OpenAI Codex CLI uses).  Standard library only.

Two ways in, one stored secret:
  * Codex bridge: read ~/.codex/auth.json (written by `codex login`) with `read_codex_session()`.
  * Browser flow: `new_pkce()` + `authorize_url()` -> user consents -> `exchange_code()`.
The secret is a dict of text fields (aistudio.secrets): access_token, refresh_token, account_id, expires_at (unix seconds as text).
`valid_secret()` refreshes an expired access token through the injectable transport (see aistudio.providers.base) and returns the new secret.
"""
import base64
import hashlib
import json
import os
import secrets as _rand
import time
import urllib.parse
from pathlib import Path

from aistudio.providers.base import AuthError, ProviderError

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
SCOPE = "openid profile email offline_access"
# Codex's registered redirect; OpenAI only accepts redirect URIs registered for the client id.
REDIRECT_URI = "http://localhost:1455/auth/callback"
SKEW = 120          # refresh this many seconds before the token expires


def codex_auth_path():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "auth.json"


def _jwt_claims(token):
    try:
        part = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception:
        return {}


def _expiry(access_token):
    exp = _jwt_claims(access_token).get("exp")
    return int(exp) if isinstance(exp, (int, float)) else int(time.time()) + 3000


def _account_id(access_token, id_token=""):
    for tok in (access_token, id_token):
        auth = _jwt_claims(tok).get("https://api.openai.com/auth") or {}
        if auth.get("chatgpt_account_id"):
            return auth["chatgpt_account_id"]
    return ""


def _plan(secret):
    auth = _jwt_claims(secret.get("access_token", "")).get("https://api.openai.com/auth") or {}
    return auth.get("chatgpt_plan_type") or ""


def _secret_from_tokens(tokens, previous=None):
    """Token endpoint / Codex file `tokens` dict -> stored secret fields."""
    prev = previous or {}
    access = tokens.get("access_token") or ""
    refresh = tokens.get("refresh_token") or prev.get("refresh_token") or ""
    if not access or not refresh:
        raise AuthError("the sign-in response had no access or refresh token")
    account = tokens.get("account_id") or _account_id(access, tokens.get("id_token") or "") or prev.get("account_id") or ""
    out = {"access_token": access, "refresh_token": refresh, "expires_at": str(_expiry(access))}
    if account:
        out["account_id"] = account
    return out


def describe(secret):
    """Safe-to-show summary of a stored session (never the tokens)."""
    exp = int(secret.get("expires_at") or 0)
    return {"signed_in": bool(secret.get("access_token")), "account_id_set": bool(secret.get("account_id")),
            "plan": _plan(secret), "expires_at": exp, "expired": bool(exp) and exp < time.time()}


# ---------------------------------------------------------------- Option A: Codex CLI session
def read_codex_session(path=None):
    """Return (secret, preview) from ~/.codex/auth.json, or raise ProviderError saying what is missing."""
    p = Path(path) if path else codex_auth_path()
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProviderError("Codex CLI is not signed in (no ~/.codex/auth.json). Run `codex login` first.") from None
    except (OSError, ValueError):
        raise ProviderError("could not read the Codex auth file") from None
    tokens = doc.get("tokens") if isinstance(doc, dict) else None
    if not isinstance(tokens, dict) or not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise ProviderError("the Codex auth file has no ChatGPT sign-in (it may use an API key); run `codex login` with ChatGPT")
    secret = _secret_from_tokens(tokens)
    return secret, describe(secret)


def codex_detected(path=None):
    try:
        read_codex_session(path)
        return True
    except ProviderError:
        return False


# ---------------------------------------------------------------- Option B: browser PKCE
def new_pkce():
    verifier = base64.urlsafe_b64encode(_rand.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return {"verifier": verifier, "challenge": challenge, "state": _rand.token_urlsafe(24)}


def authorize_url(pkce, redirect_uri=REDIRECT_URI):
    q = {"response_type": "code", "client_id": CLIENT_ID, "redirect_uri": redirect_uri, "scope": SCOPE,
         "code_challenge": pkce["challenge"], "code_challenge_method": "S256", "state": pkce["state"],
         "id_token_add_organizations": "true", "codex_cli_simplified_flow": "true", "originator": "codex_cli_rs"}
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode(q)


def exchange_code(transport, code, verifier, redirect_uri=REDIRECT_URI):
    from aistudio.providers.base import default_transport
    t = transport or default_transport()
    resp = t("POST", TOKEN_URL, headers={"Content-Type": "application/x-www-form-urlencoded"},
             body={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                   "client_id": CLIENT_ID, "code_verifier": verifier})
    return _secret_from_tokens(resp if isinstance(resp, dict) else {})


# ---------------------------------------------------------------- refresh
def needs_refresh(secret, now=None):
    exp = int(secret.get("expires_at") or 0)
    return not exp or exp - SKEW <= (now or time.time())


def refresh(transport, secret):
    from aistudio.providers.base import default_transport
    if not secret.get("refresh_token"):
        raise AuthError("ChatGPT session has no refresh token; sign in again")
    t = transport or default_transport()
    try:
        resp = t("POST", TOKEN_URL, body={"client_id": CLIENT_ID, "grant_type": "refresh_token",
                                          "refresh_token": secret["refresh_token"], "scope": "openid profile email"})
    except AuthError:
        raise
    except ProviderError as e:
        if "invalid_grant" in str(e) or "HTTP 400" in str(e) or "HTTP 401" in str(e):
            raise AuthError("ChatGPT session expired or was revoked; sign in again") from None
        raise
    return _secret_from_tokens(resp if isinstance(resp, dict) else {}, previous=secret)


def valid_secret(transport, secret, on_update=None, now=None):
    """The secret, refreshed first when the access token is (nearly) expired.  `on_update(secret)` persists a refreshed one."""
    if not needs_refresh(secret, now):
        return secret
    fresh = refresh(transport, secret)
    if on_update:
        on_update(fresh)
    return fresh
