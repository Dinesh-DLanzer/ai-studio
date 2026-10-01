"""API keys for outside tools (agents, scripts).  Standard library only.

A key (aisk_...) is shown ONCE when it is made; only its SHA-256 is stored (settings/api_keys.json, mode 0600), so it can never be read back.
A key is an AGENT key: the server lets it do what the MCP tools can do (read, write documents, estimate, propose, run what a human already
approved) and nothing that spends money by itself, approves anything, or changes providers, keys, limits or projects' existence.
"""
import hashlib
import json
import os
import secrets
import time
from datetime import datetime
from pathlib import Path

PREFIX = "aisk_"
MAX_KEYS = 20
_last_touch = {}


class KeyError_(Exception):
    pass


def _file(root):
    return Path(root) / "settings" / "api_keys.json"


def _load(root):
    f = _file(root)
    try:
        rows = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    except (OSError, ValueError):
        rows = []
    return rows if isinstance(rows, list) else []


def _save(root, rows):
    f = _file(root)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(f)


def _public(r):
    return {"id": r["id"], "name": r["name"], "prefix": r["prefix"], "created": r["created"], "last_used": r.get("last_used")}


def _hash(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def list_keys(root):
    return [_public(r) for r in _load(root)]


def create(root, name):
    """Returns (public record, the key).  The key is not stored and cannot be shown again."""
    name = str(name or "").strip()
    if not 1 <= len(name) <= 60:
        raise KeyError_("give the key a name of 1 to 60 characters")
    rows = _load(root)
    if len(rows) >= MAX_KEYS:
        raise KeyError_(f"at most {MAX_KEYS} keys: revoke one first")
    key = PREFIX + secrets.token_urlsafe(24)
    rec = {"id": secrets.token_hex(4), "name": name, "prefix": key[:len(PREFIX) + 4], "hash": _hash(key), "created": datetime.now().isoformat(timespec="seconds"), "last_used": None}
    _save(root, rows + [rec])
    return _public(rec), key


def revoke(root, kid):
    rows = _load(root)
    keep = [r for r in rows if r["id"] != kid]
    if len(keep) == len(rows):
        raise KeyError_("unknown key")
    _save(root, keep)


def verify(root, key):
    """The record of a valid key, else None.  Compares hashes in constant time; records 'last used' at most once a minute."""
    if not isinstance(key, str) or not key.startswith(PREFIX) or len(key) > 200:
        return None
    h, hit = _hash(key), None
    for r in _load(root):
        if secrets.compare_digest(h, r.get("hash", "")):
            hit = r
    if hit and time.time() - _last_touch.get(hit["id"], 0) > 60:
        _last_touch[hit["id"]] = time.time()
        rows = _load(root)
        for r in rows:
            if r["id"] == hit["id"]:
                r["last_used"] = datetime.now().isoformat(timespec="seconds")
        _save(root, rows)
    return _public(hit) if hit else None
