"""Human-facing local notifications shared by the web server and MCP process.

Approval notices live in the external AI Studio state directory, never inside a
project. The code is intentionally available only to the local human UI/terminal
channels; MCP tool responses contain only the challenge id.
"""
import json
import os
import time
from pathlib import Path

FILE = "approval_notifications.json"


def _store_dir():
    return Path(os.environ.get("AISTUDIO_SECRETS_DIR") or (Path.home() / ".aistudio"))


def _path():
    return _store_dir() / FILE


def _project_name(pdir):
    pdir = Path(pdir)
    return pdir.name


def publish_approval(pdir, code_id, code, message, ttl=600):
    """Store a pending human approval notice outside every project folder."""
    f = _path()
    try:
        items = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    except (OSError, ValueError):
        items = []
    now = time.time()
    items = [x for x in items if float(x.get("expires", 0)) > now and not x.get("used")]
    items.insert(0, {"id": code_id, "code": str(code), "message": message, "project": _project_name(pdir),
                     "created": now, "expires": now + ttl, "used": False})
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(items[:40], ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(f.parent, 0o700)
        os.chmod(f, 0o600)
    except OSError:
        pass
    return {k: v for k, v in items[0].items() if k not in {"code", "used"}}


def read_approvals(_scope=None):
    """Read active notices for the human UI, including their human-only code."""
    f = _path()
    if not f.exists():
        return []
    try:
        now = time.time()
        items = json.loads(f.read_text(encoding="utf-8"))
        return [x for x in items if float(x.get("expires", 0)) > now and not x.get("used")]
    except (OSError, ValueError, TypeError):
        return []


def mark_used(code_id):
    f = _path()
    try:
        items = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    except (OSError, ValueError):
        items = []
    for item in items:
        if item.get("id") == str(code_id):
            item["used"] = True
    try:
        f.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
