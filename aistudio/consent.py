"""Consent records for real people (and cloned voices): <project>/consent.json, a list of {subject, statement, date, kind}.

Writing is HUMAN-SESSION ONLY: the only caller is the web route marked agent=False in server/api_docs.py. There is no MCP/crew tool for it
(tests/test_cast.py pins that). Reading is free. Generation with an asset marked `real_person: true` is refused without a matching entry.
"""
import json
import hashlib
import hmac
import os
import re
from datetime import date as _date
from pathlib import Path

from aistudio import project as project_mod
from aistudio.domain.common import ServiceError, _sha

FILE = "consent.json"
KINDS = ("real_person", "voice")
LINEAGE_SECRET = "media-lineage-hmac"


def _lineage_key():
    """Use the existing external secret store; project files never carry the signing key."""
    from aistudio.secrets import SecretStore
    import secrets
    store = SecretStore()
    fields = store.get(LINEAGE_SECRET)
    if not fields.get("secret"):
        store.set(LINEAGE_SECRET, {"secret": secrets.token_urlsafe(32)})
        fields = store.get(LINEAGE_SECRET)
    return fields["secret"].encode("utf-8")


def _parents(meta):
    """Every input a derived file was made from: source_shas (several inputs, e.g. an editor render) or the single source_sha."""
    many = meta.get("source_shas")
    if isinstance(many, list) and many:
        return sorted({x for x in many if isinstance(x, str) and x})
    return [meta["source_sha"]] if meta.get("source_sha") else []


def _lineage_signature(sha, source_sha, kind, source_shas=None):
    body = {"sha": sha, "source_sha": source_sha or "", "kind": kind or ""}
    if source_shas:
        body["source_shas"] = sorted(source_shas)     # only present for multi-input files, so older signatures stay valid
    value = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hmac.new(_lineage_key(), value.encode("utf-8"), hashlib.sha256).hexdigest()


def write_lineage(pdir, path, meta, source_sha=None, kind=None, source_shas=None):
    """Write server-authenticated lineage for a media file produced by a trusted tool."""
    path = Path(path)
    digest = _sha(path)
    if not digest:
        raise ServiceError("cannot record lineage for unreadable media")
    meta = dict(meta)
    source_sha = source_sha if source_sha is not None else meta.get("source_sha", "")
    kind = kind if kind is not None else meta.get("kind", "")
    source_shas = sorted({x for x in (source_shas or []) if x}) or None
    meta.update({"source_sha": source_sha or "", "kind": kind or "", "sha": digest,
                 "lineage_hmac": _lineage_signature(digest, source_sha, kind, source_shas)})
    if source_shas:
        meta["source_shas"] = source_shas
    else:
        meta.pop("source_shas", None)
    project_mod.save_json(Path(pdir), path.relative_to(Path(pdir)).as_posix() + ".meta.json", meta)
    return meta


def _trusted_lineage(path, meta):
    digest = _sha(path)
    if not digest or meta.get("sha") != digest or not meta.get("lineage_hmac"):
        return False
    many = meta.get("source_shas")
    expected = _lineage_signature(digest, meta.get("source_sha", ""), meta.get("kind", ""), many if isinstance(many, list) else None)
    return hmac.compare_digest(str(meta["lineage_hmac"]), expected)


def _lineage_files(pdir):
    for directory, dirs, names in os.walk(Path(pdir), followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink()]
        for name in names:
            if name.endswith(".meta.json"):
                yield Path(directory) / name


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


def _project_media(pdir):
    p = Path(pdir)
    files = []
    for directory, dirs, names in os.walk(p, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink()]
        for name in names:
            path = Path(directory) / name
            if not name.endswith(".meta.json") and (path.is_file() or path.is_symlink()):
                files.append(path)
    return files


def _unverified_shas(pdir):
    """Find media without authenticated provenance or an explicit human clearance."""
    verified = set()
    verified.update(x.get("sha") for x in read(pdir)
                    if x.get("sha") and (x.get("kind") in ("real_person", "voice", "real_person_sha", "not_a_real_person_sha")))
    pipeline_kinds = {"image", "clip", "image_edit", "clip_extend", "upscale_ai", "reframe_ai", "restyle", "replace", "motion_transfer", "character_swap", "review", "tts", "music", "sfx", "lipsync", "transcribe"}
    files = _project_media(pdir)
    metadata = {}
    for path in files:
        meta_file = path.with_name(path.name + ".meta.json")
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        digest = _sha(path)
        if digest:
            metadata[digest] = (path, meta)
    changed = True
    while changed:
        changed = False
        for digest, (path, meta) in metadata.items():
            if digest in verified or meta.get("unverified"):
                continue
            source_sha = meta.get("source_sha")
            pipeline_output = (meta.get("kind") in pipeline_kinds and isinstance(meta.get("spec_hash"), str)
                               and re.fullmatch(r"[0-9a-f]{64}", meta["spec_hash"])
                               and meta.get("target") and meta.get("created") and meta.get("actor") is not None
                               and isinstance(meta.get("cost"), (int, float)))
            signed = _trusted_lineage(path, meta)
            parents = _parents(meta)
            if signed and (pipeline_output or (parents and all(x in verified for x in parents))):    # every input must be verified
                verified.add(digest)
                changed = True
    return {digest for digest, (path, _meta) in metadata.items() if digest not in verified}


MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff", ".mp4", ".mov", ".webm", ".mkv", ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


def unverified_media(pdir):
    """List unverified project media by relative file and current SHA for the human clearance UI."""
    shas = _unverified_shas(pdir)
    out = []
    for path in _project_media(pdir):
        if path.suffix.lower() not in MEDIA_SUFFIXES or any(part.startswith(".") or part == "_discarded" for part in path.relative_to(Path(pdir)).parts):
            continue                       # the clearance list shows media only, not Story.md, json docs, history or trash
        try:
            path.resolve().relative_to(Path(pdir).resolve())       # a symlink pointing outside the project is never listed
        except ValueError:
            continue
        digest = _sha(path)
        if digest in shas:
            try:
                rel = path.relative_to(Path(pdir)).as_posix()
            except ValueError:
                continue
            out.append({"file": rel, "sha": digest})
    return sorted(out, key=lambda item: item["file"])


def _inherits_bound(meta, marked, bound):
    """A derived file inherits consent only when every marked input it was made from has consent bound to it."""
    hit = [x for x in _parents(meta) if x in marked or x in bound]
    return bool(hit) and all(x in bound for x in hit if x in marked) and any(x in bound for x in hit)


def real_person_shas(pdir):
    marked = {x["sha"] for x in read(pdir) if x.get("kind") == "real_person_sha" and x.get("sha")}
    if not marked:
        return marked
    p = Path(pdir)
    changed = True
    while changed:
        changed = False
        for meta_file in _lineage_files(p):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            media_file = meta_file.with_name(meta_file.name[:-10])
            if media_file.is_file() and any(x in marked for x in _parents(meta)) and _trusted_lineage(media_file, meta):
                h = _sha(media_file)
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
        for meta_file in _lineage_files(p):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            media_file = meta_file.with_name(meta_file.name[:-10])
            if media_file.is_file() and _inherits_bound(meta, marked, bound) and _trusted_lineage(media_file, meta):
                h = _sha(media_file)
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
    known = {_sha(path) for path in _project_media(pdir)}
    for sha in shas:
        if (sha not in known or sha in unverified) and sha not in bound and sha not in cleared:
            raise ServiceError("an unverified media file needs human clearance (sha-bound consent or not-a-real-person clearance) for these exact file bytes")
    require_shas(pdir, shas)


def _asset_ids_for(rel):
    """Asset ids a media file can stand for: stills/<id>.png, <id>.v2.png, <id>_edit_a1.png, <id>_extended.mp4, <id>_final_a1.mp4."""
    stem = Path(str(rel)).stem
    return {stem, stem.split(".v")[0], stem.split("_edit_a")[0], stem.split("_extended")[0], stem.split("_final_a")[0]}


def require_inputs(pdir, files):
    """Consent check over the files that will REALLY be sent to a provider (the resolved payload list, never a re-derived one).
    1. A file a human marked as a real person needs bound consent (require_shas).
    2. An asset a human marked whose file bytes have since changed (re-encoded, cropped, replaced, round-tripped through an editor) is refused until a
       human marks, clears or records consent for the new bytes: consent never silently carries over to different bytes.
    3. An asset flagged real_person in images.json needs consent for its subject, found by the file's path or id (covers auto-attached and path refs)."""
    p = Path(pdir)
    paths = [Path(f) for f in files if f]
    records = read(p)
    marked_assets = {x.get("asset") for x in records if x.get("kind") == "real_person_sha" and x.get("asset")}
    known = {x.get("sha") for x in records if x.get("sha") and x.get("kind") in ("real_person", "voice", "real_person_sha", "not_a_real_person_sha")}
    known |= real_person_shas(p)
    shas, ids = [], set()
    images = [i for i in (json.loads((p / "images.json").read_text(encoding="utf-8")).get("images", []) if (p / "images.json").is_file() else []) if isinstance(i, dict)]
    for f in paths:
        if not f.is_file():
            continue
        sha = _sha(f)
        shas.append(sha)
        try:
            rel = f.resolve().relative_to(p.resolve()).as_posix()
        except ValueError:
            rel = f.name
        here = _asset_ids_for(rel) | {i.get("id") for i in images if i.get("out") == rel}
        ids |= here
        if sha not in known and here & marked_assets:
            raise ServiceError(f"{rel} was marked as a real person but its file bytes have changed since. A human must mark it again, clear it, or record consent "
                               "for the new file before it can be used.")
    require_shas(p, shas)
    require_assets(p, {"images": images}, sorted(i for i in ids if i))
