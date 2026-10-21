"""E2: cost log (cost_log.csv) and discard-aware totals.  Standard library only.

Contract (tests in tests/test_costlog.py):
  LOG_COLS = ["timestamp","shot","stage","model","resolution","seconds","attempt","job_id","cost","result","provider","cost_source","actor","override","quoted"]
      (provider and cost_source were added in v2; older log files without them are still read, the values are then missing/"")
  read_log(pdir: Path) -> list[dict]        rows of pdir/cost_log.csv as dicts of strings; [] if the file is missing.
  append_log(pdir: Path, row: dict) -> None  appends one row, migrating legacy headers atomically first.
      Missing columns are written as "", except new rows default actor/override to "local"/"no".
      Extra keys raise KeyError; historical rows retain blank missing metadata.
  record_result(pdir: Path, row: dict) -> None  inserts or updates one (shot, stage, attempt) row.
      Unspecified fields of an existing row are preserved; ambiguous duplicates raise ValueError.
  Both writes acquire project_lock.lock; callers must not already hold that non-reentrant lock.
  spent(pdir: Path) -> float                 sum of the "cost" column (blank counts as 0).
  split(pdir: Path) -> dict                  {"used": float, "discarded": float, "total": float}.
      A log row is DISCARDED when its clip file name "<shot>_<stage>_a<attempt>.mp4" appears in pdir/discarded.json
      (a JSON list of {"file": "<any path ending in that name>", "cost": float, "reason": str}); otherwise USED.
      Rows with stage "image" are discarded when a discarded.json entry's file stem equals the row's "shot".
      total == used + discarded; values rounded to 6 decimals.
"""
import csv
import json
import os
import tempfile
import threading
from pathlib import Path

from . import project_lock

# Also serialize threads when project_lock's platform-specific flock is unavailable.
_WRITE_LOCK = threading.Lock()

LOG_COLS = ["timestamp", "shot", "stage", "model", "resolution", "seconds", "attempt", "job_id", "cost", "result", "provider", "cost_source", "actor", "override", "quoted"]


def read_log(pdir):
    p = Path(pdir) / "cost_log.csv"
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _validate_row(row):
    for k in row:
        if k not in LOG_COLS:
            raise KeyError(k)


def _new_row(row):
    return {k: row.get(k, "local" if k == "actor" else "no" if k == "override" else "") for k in LOG_COLS}


def _rows_for_write(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames or []
        if len(set(columns)) != len(columns) or any(k not in LOG_COLS for k in columns):
            raise ValueError("Unsupported cost log header; existing data was not changed")
        rows = []
        for row in reader:
            overflow = row.pop(None, [])
            if overflow:
                # Older append_log versions wrote current-width rows under legacy
                # headers. Recover only the unambiguous canonical-prefix case.
                if columns != LOG_COLS[:len(columns)] or len(columns) + len(overflow) > len(LOG_COLS):
                    raise ValueError("Unrecognized cost log overflow; existing data was not changed")
                row.update(zip(LOG_COLS[len(columns):], overflow))
            rows.append({k: row.get(k) or "" for k in LOG_COLS})
        return rows


def _replace_rows(path, rows):
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", newline="", encoding="utf-8", dir=path.parent,
                                         prefix=".cost_log.", suffix=".tmp", delete=False) as f:
            tmp = Path(f.name)
            writer = csv.DictWriter(f, fieldnames=LOG_COLS)
            writer.writeheader()
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def append_log(pdir, row):
    _validate_row(row)
    p = Path(pdir) / "cost_log.csv"
    with _WRITE_LOCK, project_lock.lock(pdir):
        columns = []
        if p.exists():
            with p.open(newline="", encoding="utf-8") as f:
                columns = next(csv.reader(f), [])
        if columns != LOG_COLS:
            _replace_rows(p, _rows_for_write(p) + [_new_row(row)])
        else:
            with p.open("a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=LOG_COLS).writerow(_new_row(row))


def record_result(pdir, row):
    """Atomically upsert a result by nonblank shot/stage/attempt (string-normalized).

    Repeated writes of the same result do not add spend. Partial updates preserve
    existing metadata. Call outside project_lock.lock, as with append_log.
    """
    _validate_row(row)
    identity = ("shot", "stage", "attempt")
    if any(row.get(k) is None or not str(row[k]).strip() for k in identity):
        raise ValueError("A result requires nonblank shot, stage, and attempt")
    key = tuple(str(row[k]) for k in identity)
    p = Path(pdir) / "cost_log.csv"
    with _WRITE_LOCK, project_lock.lock(pdir):
        rows = _rows_for_write(p)
        matches = [r for r in rows if tuple(r[k] for k in identity) == key]
        if len(matches) > 1:
            raise ValueError("Multiple cost log rows match shot/stage/attempt")
        if matches:
            matches[0].update(row)
        else:
            rows.append(_new_row(row))
        _replace_rows(p, rows)


def spent(pdir):
    total = 0.0
    for r in read_log(pdir):
        c = r.get("cost", "")
        if c:
            total += float(c)
    return total


def _is_discarded(r, entries):
    for e in entries:
        f = e.get("file", "")
        if r.get("stage") == "image":
            if Path(f).stem == r.get("shot"):
                return True
        else:
            clip = "{}_{}_a{}.mp4".format(r.get("shot"), r.get("stage"), r.get("attempt"))
            if f.endswith(clip):
                return True
    return False


def split(pdir):
    d = Path(pdir) / "discarded.json"
    entries = json.loads(d.read_text(encoding="utf-8")) if d.exists() else []
    used = 0.0
    discarded = 0.0
    for r in read_log(pdir):
        c = r.get("cost", "")
        cost = float(c) if c else 0.0
        if _is_discarded(r, entries):
            discarded += cost
        else:
            used += cost
    used = round(used, 6)
    discarded = round(discarded, 6)
    return {"used": used, "discarded": discarded, "total": round(used + discarded, 6)}
