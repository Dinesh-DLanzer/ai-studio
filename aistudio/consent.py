"""Consent records for real people (and cloned voices): <project>/consent.json, a list of {subject, statement, date, kind}.

Writing is HUMAN-SESSION ONLY: the only caller is the web route marked agent=False in server/api_docs.py. There is no MCP/crew tool for it
(tests/test_cast.py pins that). Reading is free. Generation with an asset marked `real_person: true` is refused without a matching entry.
"""
import json
from datetime import date as _date
from pathlib import Path

from aistudio import project as project_mod
from aistudio.domain.common import ServiceError, _sha

FILE = "consent.json"
KINDS = ("real_person", "voice")


def read(pdir):
    f = Path(pdir) / FILE
    try:
        data = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else []
    except (OSError, ValueError):
        return []
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []


def record(pdir, subject, statement, kind="real_person", when=None, sha=None):
    """Append one consent entry. HUMAN channel only (never wire this to MCP, the crew or an agent route).
    With `sha` the consent is bound to those exact file bytes (the only kind that satisfies a file marked by mark_real_person)."""
    subject, statement = str(subject or "").strip(), str(statement or "").strip()
    if not subject or not statement:
        raise ServiceError("consent needs the subject's name and a statement")
    if kind not in KINDS:
        raise ServiceError(f"consent kind must be one of: {', '.join(KINDS)}")
    items = read(pdir)
    entry = {"subject": subject, "statement": statement, "date": when or _date.today().isoformat(), "kind": kind}
    if sha:
        entry["sha"] = str(sha)
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


def mark_real_person(pdir, asset_id, sha, subject=""):
    """HUMAN channel only: file bytes `sha` show a real person. From now on any paid tool touching a file with this sha needs a sha-bound consent
    entry, whatever images.json says (an agent clearing the real_person flag or renaming the asset cannot lift it)."""
    sha = str(sha or "").strip()
    if not sha:
        raise ServiceError("a file sha is required")
    items = read(pdir)
    if not any(x.get("kind") == "real_person_sha" and x.get("sha") == sha for x in items):
        items.append({"kind": "real_person_sha", "asset": str(asset_id or ""), "sha": sha, "subject": str(subject or "").strip(), "date": _date.today().isoformat()})
        project_mod.save_json(Path(pdir), FILE, items)
    return {"asset": asset_id, "sha": sha}


def real_person_shas(pdir):
    marked = {x["sha"] for x in read(pdir) if x.get("kind") == "real_person_sha" and x.get("sha")}
    if not marked:
        return marked
    p = Path(pdir)
    changed = True
    while changed:
        changed = False
        # 1. Scan .meta.json files in project media dirs
        for sub in ("stills", "clips", "videos", "audio"):
            d = p / sub
            if not d.is_dir():
                continue
            for meta_file in d.glob("*.meta.json"):
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                except Exception:
                    continue
                source_shas = set()
                if meta.get("source_sha"):
                    source_shas.add(meta["source_sha"])
                if meta.get("params", {}).get("source_sha"):
                    source_shas.add(meta["params"]["source_sha"])
                for r in meta.get("refs", []):
                    if isinstance(r, dict) and r.get("sha"):
                        source_shas.add(r["sha"])
                if any(s in marked for s in source_shas):
                    media_name = meta_file.name[:-10]
                    media_file = meta_file.parent / media_name
                    if media_file.is_file():
                        h = _sha(media_file)
                        if h and h not in marked:
                            marked.add(h)
                            changed = True
        # 2. Check <stem>.v<k> where base <stem> has sha in marked
        for sub in ("stills", "clips", "videos"):
            d = p / sub
            if not d.is_dir():
                continue
            for f in d.glob("*"):
                if f.is_file() and not f.name.endswith(".meta.json") and ".v" in f.name:
                    base_stem = f.name.split(".v")[0]
                    base_file = d / f"{base_stem}{f.suffix}"
                    if base_file.is_file():
                        base_h = _sha(base_file)
                        if base_h in marked:
                            h = _sha(f)
                            if h and h not in marked:
                                marked.add(h)
                                changed = True
    return marked


def require_shas(pdir, shas):
    """Refuse when a file whose sha a human marked as a real person has no sha-bound consent entry."""
    marked = real_person_shas(pdir)
    bound = {x.get("sha") for x in read(pdir) if x.get("kind") == "real_person" and x.get("sha")}
    
    # Expand bound consent to derived files whose source_sha has bound consent
    p = Path(pdir)
    changed = True
    while changed:
        changed = False
        for sub in ("stills", "clips", "videos", "audio"):
            d = p / sub
            if not d.is_dir():
                continue
            for meta_file in d.glob("*.meta.json"):
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                except Exception:
                    continue
                source_shas = set()
                if meta.get("source_sha"):
                    source_shas.add(meta["source_sha"])
                if meta.get("params", {}).get("source_sha"):
                    source_shas.add(meta["params"]["source_sha"])
                for r in meta.get("refs", []):
                    if isinstance(r, dict) and r.get("sha"):
                        source_shas.add(r["sha"])
                if any(s in bound for s in source_shas):
                    media_name = meta_file.name[:-10]
                    media_file = meta_file.parent / media_name
                    if media_file.is_file():
                        h = _sha(media_file)
                        if h and h not in bound:
                            bound.add(h)
                            changed = True
            for f in d.glob("*"):
                if f.is_file() and not f.name.endswith(".meta.json") and ".v" in f.name:
                    base_stem = f.name.split(".v")[0]
                    base_file = d / f"{base_stem}{f.suffix}"
                    if base_file.is_file() and _sha(base_file) in bound:
                        h = _sha(f)
                        if h and h not in bound:
                            bound.add(h)
                            changed = True

    for sha in shas:
        if sha in marked and sha not in bound:
            raise ServiceError("a file marked as a real person has no consent bound to it. A human must record consent for these exact file bytes "
                               "(POST /api/projects/<name>/consent with the file's sha); generation is refused until then.")
