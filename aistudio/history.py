"""Small, file based history for project documents. Standard library only."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


DOCUMENTS = {"shots.json", "images.json", "edit.json", "brief.json", "todos.json", "Story.md", "comments.json"}
_TS_RE = re.compile(r"^\d{8}T\d{9}Z$")


def _document(doc):
    doc = str(doc)
    if doc not in DOCUMENTS:
        raise ValueError(f"unsupported history document: {doc}")
    return doc


def _folder(pdir, doc):
    return Path(pdir) / ".history" / _document(doc)


def _timestamp():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond // 1000:03d}Z"


def _entry_path(pdir, doc, ts):
    doc = _document(doc)
    ts = str(ts)
    if not _TS_RE.fullmatch(ts):
        raise ValueError("invalid history timestamp")
    return _folder(pdir, doc) / f"{ts}{Path(doc).suffix}"


def record_previous(pdir, doc, previous, new):
    """Archive prior bytes when they differ from the new document bytes."""
    if previous is None or previous == new:
        return None
    folder = _folder(pdir, doc)
    folder.mkdir(parents=True, exist_ok=True)
    ts = _timestamp()
    target = folder / f"{ts}{Path(doc).suffix}"
    while target.exists():
        ts = _timestamp()
        target = folder / f"{ts}{Path(doc).suffix}"
    temp = target.with_name(target.name + ".tmp")
    temp.write_bytes(previous)
    temp.replace(target)
    entries = sorted(folder.glob(f"*{Path(doc).suffix}"), reverse=True)
    for expired in entries[200:]:
        expired.unlink()
    return ts


def history(pdir, doc):
    """Return archived versions, newest first."""
    folder = _folder(pdir, doc)
    if not folder.is_dir():
        return []
    out = []
    for f in sorted(folder.glob(f"*{Path(doc).suffix}"), reverse=True):
        if not _TS_RE.fullmatch(f.stem) or not f.is_file():
            continue
        data = f.read_bytes()
        out.append({"ts": f.stem, "size": len(data), "sha": hashlib.sha256(data).hexdigest()[:12]})
    return out


def read_version(pdir, doc, ts):
    """Read a history entry as UTF-8 text."""
    return _entry_path(pdir, doc, ts).read_text(encoding="utf-8")


def restore(pdir, doc, ts):
    """Restore a version as a new save, thereby archiving the current file."""
    doc = _document(doc)
    content = _entry_path(pdir, doc, ts).read_bytes()
    path = Path(pdir) / doc
    old = path.read_bytes() if path.is_file() else None
    temp = path.with_name(path.name + ".restore.tmp")
    temp.write_bytes(content)
    temp.replace(path)
    record_previous(pdir, doc, old, content)
    return content.decode("utf-8")


def diff_summary(pdir, doc, ts):
    """Compare an archived JSON document with the current file by top-level key."""
    doc = _document(doc)
    if not doc.endswith(".json"):
        raise ValueError("diff_summary is only available for JSON documents")
    before = json.loads(read_version(pdir, doc, ts))
    current = json.loads((Path(pdir) / doc).read_text(encoding="utf-8"))
    if not isinstance(before, dict) or not isinstance(current, dict):
        raise ValueError("JSON documents must be objects")
    old_keys, new_keys = set(before), set(current)
    return {
        "added": sorted(new_keys - old_keys),
        "removed": sorted(old_keys - new_keys),
        "changed": sorted(k for k in old_keys & new_keys if before[k] != current[k]),
    }
