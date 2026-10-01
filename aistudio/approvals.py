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
import json
import secrets
import time
from pathlib import Path

FILE = "proposals.json"
MAX_TRIES = 5


class ApprovalError(Exception):
    pass


def _canon(d):
    return json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def request_hash(kind, shot, model, price, payload):
    return hashlib.sha256(_canon({"kind": kind, "shot": shot, "model": model, "price": round(float(price), 6),
                                  "payload": payload}).encode("utf-8")).hexdigest()


def _load(pdir):
    f = Path(pdir) / FILE
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def _save(pdir, items):
    (Path(pdir) / FILE).write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


def _find(items, pid):
    for p in items:
        if p["id"] == pid:
            return p
    raise ApprovalError(f"unknown proposal {pid}")


def propose(pdir, kind, shot, model, price, payload, ttl=3600, reveal_code=False, now=None, summary=None):
    now = time.time() if now is None else now
    if float(price) < 0:
        raise ApprovalError("negative price")
    code = f"{secrets.randbelow(10**6):06d}"
    p = {"id": secrets.token_hex(6), "kind": kind, "shot": shot, "model": model, "price": round(float(price), 6),
         "hash": request_hash(kind, shot, model, price, payload), "created": now, "expires": now + ttl,
         "status": "pending", "tries": 0, "code_sha": hashlib.sha256(code.encode()).hexdigest(), "summary": summary or {}}
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


def reject(pdir, pid):
    items = _load(pdir)
    p = _find(items, pid)
    if p["status"] in ("pending", "approved"):
        p["status"] = "rejected"
    _save(pdir, items)


def consume(pdir, pid, kind, shot, model, price, payload, now=None):
    """Call immediately before the paid request. Raises ApprovalError unless this EXACT request was approved."""
    now = time.time() if now is None else now
    items = _load(pdir)
    p = _find(items, pid)
    if p["status"] != "approved":
        raise ApprovalError(f"proposal is {p['status']}, not approved")
    if now > p["expires"]:
        p["status"] = "expired"
        _save(pdir, items)
        raise ApprovalError("approval expired")
    if p["hash"] != request_hash(kind, shot, model, price, payload):
        p["status"] = "void"
        _save(pdir, items)
        raise ApprovalError("request changed after approval; propose again")
    p["status"] = "used"
    _save(pdir, items)
    return True
