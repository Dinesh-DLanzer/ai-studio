"""Device pairing and scoped authentication for NLE panels (Premiere, Resolve, After Effects, Blender).

Standard library only.
A 6-digit pairing code is derived via HMAC with an external secret (from aistudio/secrets.py).
The challenge id is stored WITHOUT the code. Expiry: 10 minutes, single-use, locks after 5 wrong attempts.
A confirmed device receives a scoped device token (aisd_...) returned ONCE.
Only the SHA-256 hash of the token is stored. Scoped to host + device_name, expires in 30 days, revocable.
"""
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from pathlib import Path
from datetime import datetime

from aistudio import notifications

DEVICE_PREFIX = "aisd_"
VALID_HOSTS = {"premiere", "resolve", "aftereffects", "blender"}
MAX_TRIES = 5
PAIRING_TTL = 600         # 10 minutes
DEVICE_TTL = 30 * 86400   # 30 days
_last_touch = {}


class PairingError(Exception):
    pass


def _pairing_secret(secrets_store):
    """Load or create the device pairing HMAC key in the external secret store."""
    ref = "device-pairing-hmac"
    fields = secrets_store.get(ref)
    if not fields.get("secret"):
        secrets_store.set(ref, {"secret": secrets.token_urlsafe(32)})
        fields = secrets_store.get(ref)
    return fields["secret"]


def derive_code(challenge_id, secret):
    """Derive the 6-digit pairing code from challenge id and external secret."""
    if not isinstance(secret, (bytes, bytearray)):
        secret = str(secret).encode("utf-8")
    digest = hmac.new(secret, str(challenge_id).encode("utf-8"), hashlib.sha256).digest()
    return f"{int.from_bytes(digest[:8], 'big') % 10**6:06d}"


def _challenges_file(root):
    return Path(root) / "settings" / "pairing_challenges.json"


def _devices_file(root):
    return Path(root) / "settings" / "paired_devices.json"


def _load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except (OSError, ValueError):
        return []


def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)


def start_pairing(root, secrets_store, now=None):
    """Create a new pairing challenge without storing the code. Returns (challenge_meta, code)."""
    now = time.time() if now is None else float(now)
    secret = _pairing_secret(secrets_store)
    challenge_id = secrets.token_hex(16)
    code = derive_code(challenge_id, secret)

    f = _challenges_file(root)
    items = _load_json(f)
    # Filter out expired or already used challenges
    items = [x for x in items if float(x.get("expires", 0)) > now and x.get("status") == "pending"]
    # Store challenge WITHOUT code!
    challenge_meta = {
        "id": challenge_id,
        "created": now,
        "expires": now + PAIRING_TTL,
        "status": "pending",
        "tries": 0,
    }
    items.append(challenge_meta)
    _save_json(f, items)

    # Publish notification to the human channel
    try:
        pdir = Path(root) / "pairing"
        projects_dir = Path(root) / "projects"
        if projects_dir.is_dir():
            projs = [p for p in sorted(projects_dir.glob("*")) if p.is_dir() and not p.name.startswith(".")]
            if projs:
                pdir = projs[0]
        notifications.publish_approval(
            pdir,
            challenge_id,
            code,
            f"Device pairing code: {code} (expires in 10 minutes)",
            ttl=PAIRING_TTL,
        )
    except Exception:
        pass

    # Print to interactive terminal stderr
    try:
        print(f"[AI Studio pairing] Device pairing code: {code} (expires in 10 minutes)", file=sys.stderr, flush=True)
    except Exception:
        pass

    return challenge_meta, code


def confirm_pairing(root, secrets_store, code, host, device_name, now=None):
    from aistudio import project_lock
    lockdir = Path(root) / "settings"
    lockdir.mkdir(parents=True, exist_ok=True)
    with project_lock.lock(lockdir):      # read-check-mark-used must be one atomic step across processes (single-use code)
        return _confirm_pairing(root, secrets_store, code, host, device_name, now)


def _confirm_pairing(root, secrets_store, code, host, device_name, now=None):
    """Confirm a 6-digit pairing code and return a newly issued device token (once)."""
    now = time.time() if now is None else float(now)
    host = str(host or "").strip().lower()
    if host not in VALID_HOSTS:
        raise PairingError(f"host must be one of {', '.join(sorted(VALID_HOSTS))}")

    device_name = str(device_name or "").strip()
    if not (1 <= len(device_name) <= 100):
        raise PairingError("device_name must be between 1 and 100 characters")

    secret = _pairing_secret(secrets_store)
    f = _challenges_file(root)
    items = _load_json(f)

    clean_code = str(code or "").strip()
    matched_challenge = None
    locked = any(ch.get("status") == "locked" for ch in items)

    for ch in items:
        if ch.get("status") == "locked":
            locked = True
            continue
        if ch.get("status") != "pending":
            continue
        if now > float(ch.get("expires", 0)):
            ch["status"] = "expired"
            continue
        if int(ch.get("tries", 0)) >= MAX_TRIES:
            ch["status"] = "locked"
            locked = True
            continue

        expected = derive_code(ch["id"], secret)
        if hmac.compare_digest(clean_code, expected):
            matched_challenge = ch
            break

    if matched_challenge is None:
        # Increment tries for any pending challenge
        for ch in items:
            if ch.get("status") == "pending" and float(ch.get("expires", 0)) > now:
                ch["tries"] = int(ch.get("tries", 0)) + 1
                if ch["tries"] >= MAX_TRIES:
                    ch["status"] = "locked"
                    locked = True
        _save_json(f, items)
        if locked:
            raise PairingError("pairing code locked after too many wrong tries")
        raise PairingError("wrong pairing code or expired challenge")

    # Mark matched challenge as used (single-use)
    matched_challenge["status"] = "used"
    _save_json(f, items)

    # Mark notification used
    try:
        notifications.mark_used(matched_challenge["id"])
    except Exception:
        pass

    # Issue device token
    raw_token = DEVICE_PREFIX + secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    device_id = secrets.token_hex(8)

    dev_rec = {
        "id": device_id,
        "host": host,
        "device_name": device_name,
        "prefix": raw_token[:len(DEVICE_PREFIX) + 4],
        "hash": token_hash,
        "created": now,
        "expires": now + DEVICE_TTL,
        "last_used": None,
        "revoked": False,
    }

    devs_file = _devices_file(root)
    devs = _load_json(devs_file)
    devs.append(dev_rec)
    _save_json(devs_file, devs)

    return {
        "device_token": raw_token,
        "device": {
            "id": device_id,
            "host": host,
            "device_name": device_name,
            "prefix": dev_rec["prefix"],
            "created": now,
            "expires": dev_rec["expires"],
        }
    }


def list_devices(root, now=None):
    """List public records of active paired devices."""
    f = _devices_file(root)
    devs = _load_json(f)
    out = []
    for d in devs:
        if d.get("revoked"):
            continue
        out.append({
            "id": d["id"],
            "host": d["host"],
            "device_name": d["device_name"],
            "prefix": d["prefix"],
            "created": d["created"],
            "expires": d["expires"],
            "last_used": d.get("last_used"),
        })
    return out


def revoke_device(root, device_id):
    """Revoke a paired device by id."""
    f = _devices_file(root)
    devs = _load_json(f)
    hit = False
    for d in devs:
        if d.get("id") == device_id and not d.get("revoked"):
            d["revoked"] = True
            hit = True
    if not hit:
        raise PairingError("unknown device")
    _save_json(f, devs)
    return True


def verify_device(root, token_str, now=None):
    """Verify a device token. Returns the device record if valid, else None."""
    if not isinstance(token_str, str) or not token_str.startswith(DEVICE_PREFIX) or len(token_str) > 200:
        return None
    now = time.time() if now is None else float(now)
    h = hashlib.sha256(token_str.encode("utf-8")).hexdigest()
    f = _devices_file(root)
    devs = _load_json(f)
    hit = None
    for d in devs:
        if secrets.compare_digest(h, d.get("hash", "")):
            if d.get("revoked") or now > float(d.get("expires", 0)):
                return None
            hit = d
            break

    if hit and (now - _last_touch.get(hit["id"], 0) > 60):
        _last_touch[hit["id"]] = now
        for d in devs:
            if d["id"] == hit["id"]:
                d["last_used"] = datetime.now().isoformat(timespec="seconds")
        _save_json(f, devs)

    return hit
