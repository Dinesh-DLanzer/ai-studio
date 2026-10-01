"""E2: cost log (cost_log.csv) and discard-aware totals.  Standard library only.

Contract (tests in tests/test_costlog.py):
  LOG_COLS = ["timestamp","shot","stage","model","resolution","seconds","attempt","job_id","cost","result","provider","cost_source"]
      (provider and cost_source were added in v2; older log files without them are still read, the values are then missing/"")
  read_log(pdir: Path) -> list[dict]        rows of pdir/cost_log.csv as dicts of strings; [] if the file is missing.
  append_log(pdir: Path, row: dict) -> None  appends one row (writes the header first if the file is new). Missing
      columns are written as "", extra keys raise KeyError.
  spent(pdir: Path) -> float                 sum of the "cost" column (blank counts as 0).
  split(pdir: Path) -> dict                  {"used": float, "discarded": float, "total": float}.
      A log row is DISCARDED when its clip file name "<shot>_<stage>_a<attempt>.mp4" appears in pdir/discarded.json
      (a JSON list of {"file": "<any path ending in that name>", "cost": float, "reason": str}); otherwise USED.
      Rows with stage "image" are discarded when a discarded.json entry's file stem equals the row's "shot".
      total == used + discarded; values rounded to 6 decimals.
"""
import csv
import json
from pathlib import Path

LOG_COLS = ["timestamp", "shot", "stage", "model", "resolution", "seconds", "attempt", "job_id", "cost", "result", "provider", "cost_source"]


def read_log(pdir):
    p = Path(pdir) / "cost_log.csv"
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_log(pdir, row):
    for k in row:
        if k not in LOG_COLS:
            raise KeyError(k)
    p = Path(pdir) / "cost_log.csv"
    new = not p.exists() or p.stat().st_size == 0
    with p.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_COLS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in LOG_COLS})


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
