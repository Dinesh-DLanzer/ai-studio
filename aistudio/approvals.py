"""E12: proposal / approval engine. Every paid action is PROPOSED first (nothing is spent) and runs only after a HUMAN
approves that exact proposal. Standard library only.

Design:
  * propose() stores a pending proposal in <project>/proposals.json bound to a hash of the exact request
    (kind, shot, model, price, payload). The one-time approval CODE is returned to the caller only when
    reveal_code=True (the human-facing channel: web UI / terminal). Only a SHA-256 of the code is stored, so an
    agent/MCP client that proposes without reveal_code never learns the code and cannot approve its own proposal.
  * approve() needs the code (what the human sees). Wrong code -> ApprovalError; 5 wrong tries lock the proposal.
  * consume() is called right before the paid call: it re-computes the request hash and raises unless the proposal
    is approved, unexpired, unused and the request is IDENTICAL (any change to prompt/model/price/image voids it).
    A proposal can be consumed once.
Honest limit: on a single-user local machine, a process with shell access to this folder could still read
proposals.json or call reveal_code=True. This stops accidents and MCP/agent self-approval, not a hostile local user.
"""
import hashlib
import hmac
import json
import secrets
import os
import tempfile
import time
from functools import wraps
from dataclasses import dataclass, field
from pathlib import Path

from aistudio import project_lock

FILE = "proposals.json"
MAX_TRIES = 5
_LIVE_GRANTS = {}


def _locked(fn):
    @wraps(fn)
    def wrapped(pdir, *args, **kwargs):
        with project_lock.lock(pdir):
            return fn(pdir, *args, **kwargs)
    return wrapped


def _atomic_json(path, value):
    path = Path(path)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as f:
            tmp = Path(f.name)
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


class ApprovalError(Exception):
    pass


@dataclass(frozen=True)
class Grant:
    """One-use authority issued by consuming one exact, human-approved request."""

    proposal_id: str
    request_hash: str
    price: float
    actor: str = "local"
    kind: str = ""
    _capability: str = field(default="", repr=False, compare=False)


def _canon(d):
    return json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def request_hash(kind, shot, model, price, payload):
    return hashlib.sha256(_canon({"kind": kind, "shot": shot, "model": model, "price": round(float(price), 6),
                                  "payload": payload}).encode("utf-8")).hexdigest()


def _load(pdir):
    f = Path(pdir) / FILE
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def _save(pdir, items):
    _atomic_json(Path(pdir) / FILE, items)


def _find(items, pid):
    for p in items:
        if p["id"] == pid:
            return p
    raise ApprovalError(f"unknown proposal {pid}")


@_locked
def propose(pdir, kind, shot, model, price, payload, ttl=3600, reveal_code=False, now=None, summary=None, actor="local", options=None):
    now = time.time() if now is None else now
    if float(price) < 0:
        raise ApprovalError("negative price")
    code = f"{secrets.randbelow(10**6):06d}"
    p = {"id": secrets.token_hex(6), "kind": kind, "shot": shot, "model": model, "price": round(float(price), 6),
         "hash": request_hash(kind, shot, model, price, payload), "created": now, "expires": now + ttl,
         "status": "pending", "tries": 0, "code_sha": hashlib.sha256(code.encode()).hexdigest(), "summary": summary or {}, "actor": actor, "options": options or {}}
    items = _load(pdir)
    items.append(p)
    _save(pdir, items)
    out = {k: v for k, v in p.items() if k != "code_sha"}
    if reveal_code:
        out["code"] = code
    return out


def get(pdir, pid):
    p = dict(_find(_load(pdir), pid))
    p.pop("code_sha", None)
    return p


@_locked
def approve(pdir, pid, code, now=None):
    now = time.time() if now is None else now
    items = _load(pdir)
    p = _find(items, pid)
    if p["status"] != "pending":
        raise ApprovalError(f"proposal is {p['status']}")
    if now > p["expires"]:
        p["status"] = "expired"
        _save(pdir, items)
        raise ApprovalError("proposal expired")
    if p["tries"] >= MAX_TRIES:
        raise ApprovalError("proposal locked after too many wrong codes")
    if hashlib.sha256(str(code).encode()).hexdigest() != p["code_sha"]:
        p["tries"] += 1
        _save(pdir, items)
        raise ApprovalError("wrong code")
    p["status"] = "approved"
    _save(pdir, items)
    return get(pdir, pid)


@_locked
def approve_human(pdir, pid, now=None):
    """Approval by a HUMAN-FACING channel (web UI behind the session token, or the terminal). No code needed: the channel itself
    is the proof. NEVER expose this through MCP or any agent-callable tool."""
    now = time.time() if now is None else now
    items = _load(pdir)
    p = _find(items, pid)
    if p["status"] != "pending":
        raise ApprovalError(f"proposal is {p['status']}")
    if now > p["expires"]:
        p["status"] = "expired"
        _save(pdir, items)
        raise ApprovalError("proposal expired")
    p["status"] = "approved"
    _save(pdir, items)
    return get(pdir, pid)


@_locked
def reject(pdir, pid):
    items = _load(pdir)
    p = _find(items, pid)
    if p["status"] in ("pending", "approved"):
        p["status"] = "rejected"
    _save(pdir, items)


@_locked
def consume(pdir, pid, request_hash_value=None, *, kind=None, shot=None, model=None, price=None, payload=None, now=None):
    """Consume one approved request and return a one-use :class:`Grant`.

    New callers pass the already-computed exact request hash.  The keyword form is
    retained for compatibility with older callers and independently recomputes the
    hash before issuing the grant.
    """
    now = time.time() if now is None else now
    items = _load(pdir)
    p = _find(items, pid)
    if p["status"] != "approved":
        raise ApprovalError(f"proposal is {p['status']}, not approved")
    if now > p["expires"]:
        p["status"] = "expired"
        _save(pdir, items)
        raise ApprovalError("approval expired")
    if request_hash_value is None:
        if any(v is None for v in (kind, shot, model, price, payload)):
            raise ApprovalError("exact request hash is required")
        request_hash_value = request_hash(kind, shot, model, price, payload)
    elif all(v is not None for v in (kind, shot, model, price, payload)):
        # Do not let a caller supply a hash for a different request.
        if request_hash_value != request_hash(kind, shot, model, price, payload):
            p["status"] = "void"
            _save(pdir, items)
            raise ApprovalError("request changed after approval; propose again")
    if p["hash"] != request_hash_value:
        p["status"] = "void"
        _save(pdir, items)
        raise ApprovalError("request changed after approval; propose again")
    p["status"] = "used"
    _save(pdir, items)
    grant = Grant(proposal_id=pid, request_hash=request_hash_value, price=float(p["price"]), actor=p.get("actor", "local"), kind=p.get("kind", ""), _capability=secrets.token_urlsafe(32))
    _LIVE_GRANTS[(str(Path(pdir).resolve()), pid)] = grant._capability
    return grant


def _kind_allows(role, proposal_kind):
    return proposal_kind in {
        "image": {"image", "image_edit"},
        "video": {"clip", "clip_extend", "upscale_ai", "reframe_ai", "restyle", "replace", "motion_transfer", "character_swap"},
        "vision": {"review", "character_review"},
    }.get(role, {role})


def _fallback_code(code_id, keychain_secret):
    """Derive the six-digit fallback code from the challenge id and external secret."""
    if not isinstance(keychain_secret, (bytes, bytearray)):
        keychain_secret = str(keychain_secret).encode("utf-8")
    digest = hmac.new(keychain_secret, str(code_id).encode("utf-8"), hashlib.sha256).digest()
    return f"{int.from_bytes(digest[:8], 'big') % 10**6:06d}"


@_locked
def issue_code(pdir, reference, kind, request_hash_value, keychain_secret, ttl=600, now=None):
    """Issue a short-lived out-of-band code without storing it in the project."""
    now = time.time() if now is None else now
    code_id = secrets.token_hex(16)
    code = _fallback_code(code_id, keychain_secret)
    f = Path(pdir) / "approval_challenges.json"
    try:
        items = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    except (OSError, ValueError):
        items = []
    items = [x for x in items if x.get("status") == "pending" and float(x.get("expires", 0)) > now]
    items.append({"id": code_id, "reference": str(reference), "kind": kind, "request_hash": request_hash_value,
                  "created": now, "expires": now + ttl, "status": "pending"})
    _atomic_json(f, items)
    return {"id": code_id, "code": code, "expires": now + ttl}


@_locked
def redeem_code(pdir, code_id, code, reference, kind, request_hash_value, keychain_secret, now=None):
    """Redeem exactly one fallback code, bound to the original request."""
    now = time.time() if now is None else now
    f = Path(pdir) / "approval_challenges.json"
    try:
        items = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    except (OSError, ValueError):
        items = []
    item = next((x for x in items if x.get("id") == str(code_id)), None)
    if not item or item.get("status") != "pending":
        raise ApprovalError("unknown or already used approval code")
    if now > float(item.get("expires", 0)):
        item["status"] = "expired"
        _atomic_json(f, items)
        raise ApprovalError("approval code expired")
    if (item.get("reference"), item.get("kind"), item.get("request_hash")) != (str(reference), kind, request_hash_value):
        raise ApprovalError("approval code is bound to a different request")
    if not hmac.compare_digest(str(code), _fallback_code(code_id, keychain_secret)):
        item["tries"] = int(item.get("tries", 0)) + 1
        if item["tries"] >= MAX_TRIES:
            item["status"] = "locked"       # a 6-digit code must not be guessable by a looping agent
        _atomic_json(f, items)
        raise ApprovalError("approval code locked after too many wrong tries" if item["status"] == "locked" else "wrong approval code")
    item["status"] = "used"
    _atomic_json(f, items)
    return True


@_locked
def redeem(pdir, grant, kind):
    """Redeem a live grant at the paid boundary; each grant can be redeemed once."""
    if not isinstance(grant, Grant):
        raise ApprovalError("invalid grant")
    key = (str(Path(pdir).resolve()), grant.proposal_id)
    if not grant._capability or _LIVE_GRANTS.get(key) != grant._capability:
        raise ApprovalError("grant is not a live approval capability")
    items = _load(pdir)
    p = _find(items, grant.proposal_id)
    if p.get("status") != "used":
        raise ApprovalError("grant proposal is not consumed")
    if p.get("redeemed"):
        raise ApprovalError("grant was already redeemed")
    if p.get("hash") != grant.request_hash or p.get("kind") != grant.kind:
        raise ApprovalError("grant does not match the consumed request")
    if float(p.get("price", 0)) != float(grant.price) or not _kind_allows(kind, grant.kind):
        raise ApprovalError("grant is for a different paid role")
    p["redeemed"] = True
    _save(pdir, items)
    _LIVE_GRANTS.pop(key, None)
    return grant
