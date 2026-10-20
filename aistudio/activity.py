"""Activity and live process tracking for AI Studio projects.
Shared across Web UI, MCP, and CLI processes via project directory state.
"""
import json
import time
from pathlib import Path

ACTIVITY_FILE = ".activity.json"


def record_start(pdir: Path, pid: str, kind: str, target: str, model: str, price: float, source: str = "mcp") -> dict:
    items = load_activity(pdir)
    # Prune completed jobs older than 5 minutes
    cutoff = time.time() - 300
    items = [x for x in items if x.get("status") == "running" or x.get("updated_at", 0) > cutoff]
    
    job = {
        "id": pid,
        "kind": kind,
        "target": target,
        "model": model,
        "price": price,
        "status": "running",
        "started_at": time.time(),
        "updated_at": time.time(),
        "source": source,
    }
    # Deduplicate by id
    items = [x for x in items if x.get("id") != pid]
    items.insert(0, job)
    save_activity(pdir, items)
    return job


def record_finish(pdir: Path, pid: str, status: str = "done", result: dict = None, error: str = None) -> None:
    items = load_activity(pdir)
    now = time.time()
    for x in items:
        if x.get("id") == pid:
            x["status"] = status
            x["updated_at"] = now
            x["completed_at"] = now
            if result:
                x["result"] = result
            if error:
                x["error"] = error
            break
    save_activity(pdir, items)


def load_activity(pdir: Path) -> list:
    f = pdir / ACTIVITY_FILE
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        # Auto-expire stale running jobs after 10 minutes
        now = time.time()
        changed = False
        for x in data:
            if x.get("status") == "running" and now - x.get("started_at", 0) > 600:
                x["status"] = "timeout"
                x["error"] = "Generation timed out"
                x["updated_at"] = now
                changed = True
        if changed:
            save_activity(pdir, data)
        return data
    except Exception:
        return []


def save_activity(pdir: Path, items: list) -> None:
    f = pdir / ACTIVITY_FILE
    try:
        pdir.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(f)
    except Exception:
        pass
