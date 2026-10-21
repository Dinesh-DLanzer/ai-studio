"""Comments and reviewer feedback domain for AI Studio.

Structure in <project>/comments.json:
{
  "schema_version": 1,
  "comments": [
    {
      "id": "c_...",
      "target": "edit" | "shot:<ID>" | "asset:<ID>",
      "time": 12.4,
      "author": "Priya (reviewer)",
      "text": "...",
      "status": "open" | "resolved",
      "created": "2026-10-21T14:00:00Z",
      "source": "reviewer" (optional)
    }
  ]
}
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, List, Optional
import uuid

from pydantic import Field
from aistudio import project as project_mod
from aistudio.domain.common import ServiceError
from aistudio.schemas.base import SchemaModel

MAX_TEXT_LEN = 2000
MAX_AUTHOR_LEN = 64
MAX_COMMENTS_IMPORT = 500
MAX_FEEDBACK_BYTES = 1024 * 1024  # 1 MB

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TARGET_RE = re.compile(r"^(edit|shot:[A-Za-z0-9_-]{1,64}|asset:[A-Za-z0-9_-]{1,64})$")


def strip_control_chars(s: str, allow_newlines: bool = False) -> str:
    """Strip ASCII control characters (< 32 and 127).

    If allow_newlines is True, newlines (\\n) and tabs (\\t) are retained.
    """
    if not isinstance(s, str):
        return ""
    out = []
    for ch in s:
        cp = ord(ch)
        if allow_newlines and ch in ("\n", "\t"):
            out.append(ch)
        elif cp < 32 or cp == 127:
            continue
        else:
            out.append(ch)
    return "".join(out)


def clean_id(raw_id: str) -> str:
    raw = str(raw_id or "").strip()
    if not ID_RE.match(raw):
        raise ValueError(f"invalid comment id: {raw_id!r} (must match {ID_RE.pattern})")
    return raw


def clean_target(raw_target: str) -> str:
    raw = str(raw_target or "").strip()
    if not TARGET_RE.match(raw):
        raise ValueError(f"invalid comment target: {raw_target!r} (must be 'edit', 'shot:<id>', or 'asset:<id>')")
    return raw


def clean_author(raw_author: str) -> str:
    raw = strip_control_chars(str(raw_author or ""), allow_newlines=False).strip()
    if not raw:
        raise ValueError("comment author display name cannot be empty")
    if len(raw) > MAX_AUTHOR_LEN:
        raise ValueError(f"comment author exceeds maximum length of {MAX_AUTHOR_LEN} characters")
    return raw


def clean_text(raw_text: str) -> str:
    raw = strip_control_chars(str(raw_text or ""), allow_newlines=True).strip()
    if not raw:
        raise ValueError("comment text cannot be empty")
    if len(raw) > MAX_TEXT_LEN:
        raise ValueError(f"comment text exceeds maximum length of {MAX_TEXT_LEN} characters")
    return raw


def clean_time(raw_time: Any) -> Optional[float]:
    if raw_time is None or raw_time == "":
        return None
    try:
        t = float(raw_time)
    except (TypeError, ValueError):
        raise ValueError(f"invalid comment timecode: {raw_time!r}") from None
    if t < 0:
        raise ValueError("comment timecode cannot be negative")
    return round(t, 2)


def clean_status(raw_status: str) -> str:
    st = str(raw_status or "open").strip().lower()
    if st not in ("open", "resolved"):
        raise ValueError(f"invalid comment status: {raw_status!r} (must be 'open' or 'resolved')")
    return st


class CommentItem(SchemaModel):
    id: str
    target: str
    time: Optional[float] = None
    author: str
    text: str
    status: str = "open"
    created: str
    source: Optional[str] = None


class CommentsDoc(SchemaModel):
    schema_version: int = 1
    comments: List[CommentItem] = Field(default_factory=list)


def validate_comments_doc(doc: Any) -> List[str]:
    """Pure validator for comments.json (e.g. used by importzip). Returns list of error strings."""
    errors = []
    if not isinstance(doc, dict):
        return ["comments document must be a JSON object"]
    version = doc.get("schema_version")
    if version != 1:
        errors.append(f"unsupported schema_version: {version}")
    raw_comments = doc.get("comments")
    if not isinstance(raw_comments, list):
        errors.append("comments must be a list")
        return errors
    for idx, c in enumerate(raw_comments):
        if not isinstance(c, dict):
            errors.append(f"comment #{idx} must be an object")
            continue
        try:
            clean_id(c.get("id"))
        except ValueError as e:
            errors.append(f"comment #{idx}: {e}")
        try:
            clean_target(c.get("target"))
        except ValueError as e:
            errors.append(f"comment #{idx}: {e}")
        try:
            clean_author(c.get("author"))
        except ValueError as e:
            errors.append(f"comment #{idx}: {e}")
        try:
            clean_text(c.get("text"))
        except ValueError as e:
            errors.append(f"comment #{idx}: {e}")
        try:
            clean_time(c.get("time"))
        except ValueError as e:
            errors.append(f"comment #{idx}: {e}")
        try:
            clean_status(c.get("status", "open"))
        except ValueError as e:
            errors.append(f"comment #{idx}: {e}")
    return errors


def load_comments_doc(data: Any) -> dict:
    """Migrate and validate comments document while preserving unknown keys."""
    from copy import deepcopy

    if not isinstance(data, dict):
        raise TypeError("comments document must be an object")
    original = deepcopy(data)
    version = original.get("schema_version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version != 1:
        raise ValueError(f"unsupported comments schema_version: {version!r}")
    validated = CommentsDoc.model_validate(original)
    merged = original
    merged.update(validated.model_dump(by_alias=True, exclude_unset=True))
    return merged


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gen_id() -> str:
    return f"c_{uuid.uuid4().hex[:12]}"


def load_comments(pdir: Path | str) -> dict:
    """Load and migrate comments.json from project folder."""
    pdir = Path(pdir)
    f = pdir / "comments.json"
    if not f.is_file():
        return {"schema_version": 1, "comments": []}
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ServiceError(f"invalid comments.json: {e}") from None
    return load_comments_doc(raw)


def save_comments(pdir: Path | str, doc: dict) -> dict:
    """Save comments.json via schema- and history-aware path."""
    pdir = Path(pdir)
    normalized = load_comments_doc(doc)
    project_mod.save_json(pdir, "comments.json", normalized)
    return normalized


def list_comments(pdir: Path | str, target: Optional[str] = None, status: Optional[str] = None) -> List[dict]:
    """List comments in a project, optionally filtered by target or status."""
    doc = load_comments(pdir)
    items = doc.get("comments", [])
    if target:
        items = [c for c in items if c.get("target") == target]
    if status:
        items = [c for c in items if c.get("status") == status]
    return items


def add_comment(
    pdir: Path | str,
    target: str,
    text: str,
    author: str,
    time: Optional[float] = None,
    cid: Optional[str] = None,
    source: Optional[str] = None,
) -> dict:
    """Add a new comment to comments.json."""
    c_id = clean_id(cid or _gen_id())
    c_target = clean_target(target)
    c_author = clean_author(author)
    c_text = clean_text(text)
    c_time = clean_time(time)

    doc = load_comments(pdir)
    comments_list = doc.setdefault("comments", [])

    if any(c.get("id") == c_id for c in comments_list):
        raise ValueError(f"a comment with id {c_id!r} already exists")

    comment = {
        "id": c_id,
        "target": c_target,
        "time": c_time,
        "author": c_author,
        "text": c_text,
        "status": "open",
        "created": _now_iso(),
    }
    if source:
        comment["source"] = clean_id(source) if ID_RE.match(source) else "reviewer"

    comments_list.append(comment)
    save_comments(pdir, doc)
    return comment


def resolve_comment(pdir: Path | str, cid: str) -> dict:
    """Mark a comment as resolved."""
    cid = clean_id(cid)
    doc = load_comments(pdir)
    for c in doc.get("comments", []):
        if c.get("id") == cid:
            c["status"] = "resolved"
            save_comments(pdir, doc)
            return c
    raise ServiceError(f"comment {cid!r} not found")


def reopen_comment(pdir: Path | str, cid: str) -> dict:
    """Mark a resolved comment as open."""
    cid = clean_id(cid)
    doc = load_comments(pdir)
    for c in doc.get("comments", []):
        if c.get("id") == cid:
            c["status"] = "open"
            save_comments(pdir, doc)
            return c
    raise ServiceError(f"comment {cid!r} not found")


def delete_comment(pdir: Path | str, cid: str) -> dict:
    """Delete a comment by id."""
    cid = clean_id(cid)
    doc = load_comments(pdir)
    comments_list = doc.get("comments", [])
    idx = next((i for i, c in enumerate(comments_list) if c.get("id") == cid), None)
    if idx is None:
        raise ServiceError(f"comment {cid!r} not found")
    removed = comments_list.pop(idx)
    save_comments(pdir, doc)
    return {"id": cid, "deleted": True, "comment": removed}


def import_feedback(ws_or_pdir: Any, project: Any = None, json_text: Any = None) -> dict:
    """Import reviewer feedback and merge comments into the project.

    Merges comments with source='reviewer'.
    Caps: size <= 1 MB, comments <= 500.
    Dedupes by id. Never executes anything.
    """
    if json_text is None and isinstance(project, (str, bytes)):
        pdir = Path(ws_or_pdir)
        raw = project
    else:
        if hasattr(ws_or_pdir, "pdir"):
            pdir = ws_or_pdir.pdir(project)
        else:
            pdir = Path(ws_or_pdir) / str(project) if project else Path(ws_or_pdir)
        raw = json_text

    if isinstance(raw, str):
        raw_bytes = raw.encode("utf-8")
    elif isinstance(raw, bytes):
        raw_bytes = raw
    else:
        raise ValueError("feedback content must be a string or bytes")

    if len(raw_bytes) > MAX_FEEDBACK_BYTES:
        raise ValueError(f"feedback payload exceeds maximum size limit ({MAX_FEEDBACK_BYTES // (1024 * 1024)} MB)")

    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"invalid feedback JSON: {e}") from None

    if isinstance(data, list):
        incoming = data
    elif isinstance(data, dict):
        incoming = data.get("comments")
        if incoming is None:
            raise ValueError("feedback JSON must contain a 'comments' array")
    else:
        raise ValueError("feedback JSON must be an object or array")

    if not isinstance(incoming, list):
        raise ValueError("comments in feedback must be an array")

    if len(incoming) > MAX_COMMENTS_IMPORT:
        raise ValueError(f"feedback contains too many comments ({len(incoming)}; maximum is {MAX_COMMENTS_IMPORT})")

    doc = load_comments(pdir)
    existing_list = doc.setdefault("comments", [])
    existing_ids = {c.get("id") for c in existing_list if c.get("id")}

    imported = 0
    for idx, raw_item in enumerate(incoming):
        if not isinstance(raw_item, dict):
            raise ValueError(f"feedback comment #{idx} must be an object")
        cid = clean_id(raw_item.get("id") or _gen_id())
        if cid in existing_ids:
            # Deduped by id
            continue

        comment = {
            "id": cid,
            "target": clean_target(raw_item.get("target")),
            "time": clean_time(raw_item.get("time")),
            "author": clean_author(raw_item.get("author") or "Reviewer"),
            "text": clean_text(raw_item.get("text")),
            "status": clean_status(raw_item.get("status", "open")),
            "created": raw_item.get("created") if isinstance(raw_item.get("created"), str) else _now_iso(),
            "source": "reviewer",
        }
        existing_list.append(comment)
        existing_ids.add(cid)
        imported += 1

    save_comments(pdir, doc)
    return {"imported": imported, "total": len(existing_list), "comments": existing_list}
