"""Consent records for real people (and cloned voices): <project>/consent.json, a list of {subject, statement, date, kind}.

Writing is HUMAN-SESSION ONLY: the only caller is the web route marked agent=False in server/api_docs.py. There is no MCP/crew tool for it
(tests/test_cast.py pins that). Reading is free. Generation with an asset marked `real_person: true` is refused without a matching entry.
"""
import json
import re
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


def clear_sha(pdir, sha, clearance):
    """Record a human-reviewed clearance for exact media bytes."""
    sha = str(sha or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ServiceError("a valid file sha is required")
    if clearance != "not_a_real_person":
        raise ServiceError("clearance must be not_a_real_person")
    items = read(pdir)
    if not any(x.get("kind") == "not_a_real_person_sha" and x.get("sha") == sha for x in items):
        items.append({"kind": "not_a_real_person_sha", "sha": sha, "date": _date.today().isoformat()})
        project_mod.save_json(Path(pdir), FILE, items)
    return {"sha": sha, "clearance": clearance}


def _registered_media(pdir):
    p = Path(pdir)
    registered = set()
    for filename, keys in (("images.json", ("out",)), ("shots.json", ("final_clip", "video", "clip", "first_frame", "end_frame", "final_video"))):
        try:
            doc = json.loads((p / filename).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = doc.get("images", []) if filename == "images.json" else doc.get("shots", [])
        for row in rows:
            if isinstance(row, dict):
                for key in keys:
                    rel = row.get(key)
                    if isinstance(rel, str) and rel:
                        try:
                            path = (p / rel).resolve()
                            path.relative_to(p.resolve())
                            registered.add(path)
                        except (OSError, ValueError):
                            pass
    return registered


def _unverified_shas(pdir):
    """Find media without a project registration or a chain back to registered media."""
    p = Path(pdir)
    registered = _registered_media(p)
    verified = set()
    pipeline_kinds = {"image", "clip", "image_edit", "clip_extend", "upscale_ai", "reframe_ai", "restyle", "replace", "motion_transfer", "character_swap", "review", "tts", "music", "sfx", "lipsync", "transcribe"}
    media_ext = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif",
                 ".mp4", ".mov", ".mkv", ".webm", ".mp3", ".wav", ".m4a", ".aac", ".flac"}
    files = []
    for sub in ("stills", "clips", "videos", "audio", "exports"):
        d = p / sub
        if d.is_dir():
            files.extend(f for f in d.rglob("*") if f.is_file() and f.suffix.lower() in media_ext)
    metadata = {}
    for path in files:
        meta_file = path.with_name(path.name + ".meta.json")
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        metadata[_sha(path)] = meta
        if path.resolve() in registered:
            verified.add(_sha(path))
    changed = True
    while changed:
        changed = False
        for digest, meta in metadata.items():
            if digest in verified or meta.get("unverified"):
                continue
            sources = {meta.get("source_sha"), (meta.get("params") or {}).get("source_sha")}
            sources.update(r.get("sha") for r in meta.get("refs", []) if isinstance(r, dict))
            pipeline_output = (meta.get("kind") in pipeline_kinds and isinstance(meta.get("spec_hash"), str)
                               and re.fullmatch(r"[0-9a-f]{64}", meta["spec_hash"])
                               and meta.get("target") and meta.get("created") and meta.get("actor") is not None
                               and isinstance(meta.get("cost"), (int, float)))
            if meta.get("editor_render") is True or pipeline_output or sources.intersection(verified):
                verified.add(digest)
                changed = True
    return {_sha(path) for path in files if _sha(path) not in verified}


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
    records = read(pdir)
    bound = {x.get("sha") for x in records if x.get("kind") in ("real_person", "voice") and x.get("sha")}
    cleared = {x.get("sha") for x in records if x.get("kind") == "not_a_real_person_sha" and x.get("sha")}
    
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


def require_verified_shas(pdir, shas):
    """Require provenance or a human sha clearance before consent-sensitive use."""
    records = read(pdir)
    bound = {x.get("sha") for x in records if x.get("kind") in ("real_person", "voice") and x.get("sha")}
    cleared = {x.get("sha") for x in records if x.get("kind") == "not_a_real_person_sha" and x.get("sha")}
    unverified = _unverified_shas(pdir)
    for sha in shas:
        if sha in unverified and sha not in bound and sha not in cleared:
            raise ServiceError("an unverified media file needs human clearance (sha-bound consent or not-a-real-person clearance) for these exact file bytes")
    require_shas(pdir, shas)
