"""Consent records for real people (and cloned voices): <project>/consent.json, a list of {subject, statement, date, kind}.

Writing is HUMAN-SESSION ONLY: the only caller is the web route marked agent=False in server/api_docs.py. There is no MCP/crew tool for it
(tests/test_cast.py pins that). Reading is free. Generation with an asset marked `real_person: true` is refused without a matching entry.
"""
import json
from datetime import date as _date
from pathlib import Path

from aistudio import project as project_mod
from aistudio.domain.common import ServiceError

FILE = "consent.json"
KINDS = ("real_person", "voice")


def read(pdir):
    f = Path(pdir) / FILE
    try:
        data = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else []
    except (OSError, ValueError):
        return []
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []


def record(pdir, subject, statement, kind="real_person", when=None):
    """Append one consent entry. HUMAN channel only (never wire this to MCP, the crew or an agent route)."""
    subject, statement = str(subject or "").strip(), str(statement or "").strip()
    if not subject or not statement:
        raise ServiceError("consent needs the subject's name and a statement")
    if kind not in KINDS:
        raise ServiceError(f"consent kind must be one of: {', '.join(KINDS)}")
    items = read(pdir)
    entry = {"subject": subject, "statement": statement, "date": when or _date.today().isoformat(), "kind": kind}
    items.append(entry)
    project_mod.save_json(Path(pdir), FILE, items)
    return entry


def has(pdir, subject, kind="real_person"):
    s = str(subject or "").strip().lower()
    return any(x.get("kind") == kind and str(x.get("subject", "")).strip().lower() == s for x in read(pdir))


def require(pdir, subject, kind="real_person"):
    if not has(pdir, subject, kind):
        raise ServiceError(f"{subject} is marked as a real person but has no consent record. A human must record consent first "
                           f"(POST /api/projects/<name>/consent from the page); generation is refused until then.")


def require_assets(pdir, images_doc, ids):
    """Refuse when any asset in `ids` is flagged real_person without consent for its subject (default: its id)."""
    by = {i.get("id"): i for i in images_doc.get("images", []) if isinstance(i, dict)}
    for aid in ids:
        a = by.get(aid)
        if a and a.get("real_person"):
            require(pdir, a.get("subject") or aid)
