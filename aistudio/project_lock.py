"""Cross-process project spend lock and short-lived spend reservations."""
import json
import math
import os
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def lock(pdir):
    """Serialize gate/approval/reservation state for one project across processes."""
    path = Path(pdir) / ".spend.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("a+")
    try:
        try:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError) as error:
            raise RuntimeError("Project spend lock unavailable; refusing unsafe execution") from error
        yield
    finally:
        try:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass
        fh.close()


def read_reservations(pdir):
    path = Path(pdir) / "spend_reservations.json"
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError("Spend reservations are unreadable; refusing unsafe execution") from error
    if not isinstance(rows, list):
        raise RuntimeError("Spend reservations are invalid; refusing unsafe execution")
    for row in rows:
        if not isinstance(row, dict) or not row.get("proposal_id"):
            raise RuntimeError("Spend reservations are invalid; refusing unsafe execution")
        try:
            price = float(row.get("price", 0) or 0)
        except (TypeError, ValueError) as error:
            raise RuntimeError("Spend reservations are invalid; refusing unsafe execution") from error
        if not math.isfinite(price) or price < 0:
            raise RuntimeError("Spend reservations are invalid; refusing unsafe execution")
    return rows


def write_reservations(pdir, rows):
    path = Path(pdir) / "spend_reservations.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def reserve(pdir, proposal_id, price, actor="local", *, shot="", stage="", attempt=0, model="", provider=""):
    rows = [x for x in read_reservations(pdir) if x.get("proposal_id") != proposal_id]
    rows.append({"proposal_id": proposal_id, "price": float(price), "actor": actor, "created": time.time(),
                 "shot": shot, "stage": stage, "attempt": attempt, "model": model, "provider": provider, "cost_source": "estimated"})
    write_reservations(pdir, rows)


def release(pdir, proposal_id):
    rows = [x for x in read_reservations(pdir) if x.get("proposal_id") != proposal_id]
    if rows:
        write_reservations(pdir, rows)
    else:
        try:
            (Path(pdir) / "spend_reservations.json").unlink()
        except FileNotFoundError:
            pass


def reserved(pdir):
    return sum(float(x.get("price", 0) or 0) for x in read_reservations(pdir))
