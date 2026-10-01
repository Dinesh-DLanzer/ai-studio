"""E3: discard and restore.  NEVER deletes a file.  Standard library only.

Contract (tests in tests/test_discard.py):
  discard_file(pdir: Path, rel: str, reason: str = "", cost: float = 0.0) -> dict
      Moves pdir/rel into a "_discarded" folder next to it (pdir/clips/a.mp4 -> pdir/clips/_discarded/a.mp4).
      If a file with that name is already in _discarded, keep both: the new one gets a numeric suffix
      ("a__2.mp4", "a__3.mp4", ...).  Appends {"file": <new path relative to pdir, with '/'>, "cost": cost,
      "reason": reason, "when": ISO timestamp, "original": rel} to pdir/discarded.json (a JSON list, created if
      missing) and returns that record.  Raises FileNotFoundError if the file is missing, ValueError if rel is
      absolute, contains '..', or points outside pdir, or is already inside a _discarded folder.
  restore_file(pdir: Path, rel_discarded: str) -> Path
      Moves the file back to its "original" path (from discarded.json) and removes that record from discarded.json.
      Raises FileExistsError if something already exists at the original path; FileNotFoundError if unknown.
      Returns the restored path.
  list_discarded(pdir: Path) -> list[dict]   the records ([] if none).
"""
from pathlib import Path
import json
import shutil
from datetime import datetime


def _check(pdir, rel):
    rel = str(rel)
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"invalid rel: {rel}")
    if "_discarded" in p.parts:
        raise ValueError(f"already discarded: {rel}")
    root = pdir.resolve()
    target = (pdir / p).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"outside pdir: {rel}")
    if not (pdir / p).exists():
        raise FileNotFoundError(rel)
    return pdir / p


def _load(pdir):
    f = pdir / "discarded.json"
    if not f.exists():
        return []
    return json.loads(f.read_text(encoding="utf-8"))


def _save(pdir, records):
    (pdir / "discarded.json").write_text(json.dumps(records, indent=2), encoding="utf-8")


def discard_file(pdir, rel, reason="", cost=0.0):
    src = _check(pdir, rel)
    ddir = src.parent / "_discarded"
    ddir.mkdir(exist_ok=True)
    dst = ddir / src.name
    if dst.exists():
        stem, suffix = src.stem, src.suffix
        n = 2
        while dst.exists():
            dst = ddir / f"{stem}__{n}{suffix}"
            n += 1
    shutil.move(str(src), str(dst))
    rec = {
        "file": dst.relative_to(pdir).as_posix(),
        "cost": cost,
        "reason": reason,
        "when": datetime.now().isoformat(),
        "original": Path(rel).as_posix(),
    }
    records = _load(pdir)
    records.append(rec)
    _save(pdir, records)
    return rec


def restore_file(pdir, rel_discarded):
    records = _load(pdir)
    idx = None
    for i, rec in enumerate(records):
        if rec["file"] == str(rel_discarded):
            idx = i
            break
    if idx is None:
        raise FileNotFoundError(rel_discarded)
    rec = records[idx]
    src = pdir / rec["file"]
    if not src.exists():
        raise FileNotFoundError(rel_discarded)
    orig = Path(rec["original"])
    if orig.is_absolute() or ".." in orig.parts or "_discarded" in orig.parts:
        raise ValueError(f"unsafe original path in discarded.json: {rec['original']}")
    dst = pdir / orig
    if dst.exists():
        raise FileExistsError(rec["original"])
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    del records[idx]
    _save(pdir, records)
    return dst


def list_discarded(pdir):
    return _load(pdir)
