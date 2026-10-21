"""The durable job ledger: every long-running piece of work is a row, so a restart, a closed tab or another process can still see it.

A job only EXECUTES something a human already approved, through the normal pipeline (Grant, project lock, reservations, cost log).
A job never approves anything.  A Grant lives only in the process that redeemed it, so after a restart a paid job that was running
becomes needs_sync (it may already have been billed) and is never run again by the ledger.

States: queued, running, provider_pending (the provider still renders it; polled through the existing sync path), completed, failed,
cancelled, needs_sync.  All SQL lives in aistudio/store.py.
"""
import json
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from aistudio import costlog, store
from aistudio.domain.common import ServiceError

STATES = ("queued", "running", "provider_pending", "completed", "failed", "cancelled", "needs_sync")
FINAL = ("completed", "failed", "cancelled", "needs_sync")
FREE_KINDS = ("export",)            # local work with no provider cost: safe to run again after a restart
KEEP_DAYS = 30
DEFAULT_CONCURRENCY = 2
COLS = ("id", "tenant_id", "actor", "project", "kind", "target", "proposal_id", "batch_id", "state", "provider", "model", "provider_job",
        "progress", "error", "created", "updated", "attempts", "payload", "result", "cancel_requested")


class Cancelled(Exception):
    pass


def _row(r):
    for k in ("payload", "result"):
        r[k] = json.loads(r[k]) if r[k] else None
    return r


# ---------------------------------------------------------------- ledger functions (any process)
def enqueue(root, project, kind, target="", proposal_id="", batch_id="", actor=store.ACTOR, provider="", model="", payload=None, state="queued"):
    now = time.time()
    jid = secrets.token_hex(5)
    store.execute(root, f"INSERT INTO jobs ({', '.join(COLS)}) VALUES ({', '.join('?' * len(COLS))})",
                  (jid, store.TENANT, actor, project, kind, target, proposal_id, batch_id, state, provider, model, "", 0.0, "", now, now,
                   1 if state == "running" else 0, json.dumps(payload or {}), "", 0))
    return get(root, jid)


def get(root, jid):
    rows = store.query(root, "SELECT * FROM jobs WHERE id = ? AND tenant_id = ?", (jid, store.TENANT))
    return _row(rows[0]) if rows else None


def list_jobs(root, project=None, state=None, batch_id=None, limit=200):
    sql, args = "SELECT * FROM jobs WHERE tenant_id = ?", [store.TENANT]
    for col, val in (("project", project), ("state", state), ("batch_id", batch_id)):
        if val:
            sql += f" AND {col} = ?"
            args.append(val)
    return [_row(r) for r in store.query(root, sql + " ORDER BY created DESC, id LIMIT ?", (*args, int(limit)))]


def claim(root, jid):
    """queued -> running, atomically.  False if somebody else got it or it was cancelled meanwhile."""
    return store.execute(root, "UPDATE jobs SET state = 'running', attempts = attempts + 1, updated = ? WHERE id = ? AND state = 'queued'",
                         (time.time(), jid)) == 1


def update(root, jid, **fields):
    assert set(fields) <= {"progress", "provider", "model", "provider_job", "error", "state", "result", "cancel_requested"}, fields
    if "result" in fields:
        fields["result"] = json.dumps(fields["result"], default=str)
    cols = ", ".join(f"{k} = ?" for k in fields)
    store.execute(root, f"UPDATE jobs SET {cols}, updated = ? WHERE id = ?", (*fields.values(), time.time(), jid))


def finish(root, jid, state, result=None, error=""):
    assert state in FINAL or state == "provider_pending", state
    update(root, jid, state=state, error=error, **({"result": result} if result is not None else {}), **({"progress": 100.0} if state == "completed" else {}))


def cancel(root, jid):
    """Queued: cancelled at once.  Provider-pending: we stop watching it, but the provider may still bill.  Running: asked to stop."""
    with store.transaction(root) as tx:
        rows = tx.query("SELECT state FROM jobs WHERE id = ? AND tenant_id = ?", (jid, store.TENANT))
        if not rows:
            return None
        state, now = rows[0]["state"], time.time()
        if state == "queued":
            tx.execute("UPDATE jobs SET state = 'cancelled', updated = ? WHERE id = ?", (now, jid))
        elif state == "provider_pending":
            tx.execute("UPDATE jobs SET state = 'cancelled', cancel_requested = 1, error = ?, updated = ? WHERE id = ?",
                       ("cancel requested; the provider may still bill for this job", now, jid))
        elif state == "running":
            tx.execute("UPDATE jobs SET cancel_requested = 1, updated = ? WHERE id = ?", (now, jid))
    return get(root, jid)


def prune(root, days=KEEP_DAYS):
    return store.execute(root, "DELETE FROM jobs WHERE state IN ('completed','failed','cancelled') AND updated < ?", (time.time() - days * 86400,))


def error_text(e):
    return str(e) if isinstance(e, ServiceError) else f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- the worker (server process only)
class JobRunner:
    """handlers: {kind: fn(job, progress) -> result dict}.  The handler must call the normal pipeline (e.g. ws.execute), which re-checks the
    approval itself.  concurrency(provider) -> int caps simultaneous jobs per provider (default 2).  poll(job) -> None | 'completed' | 'failed'
    is asked every poll_interval seconds about provider_pending jobs."""

    def __init__(self, root, handlers, concurrency=None, poll=None, poll_interval=15.0, workers=16):
        self.root, self.handlers, self.poll, self.poll_interval = root, handlers, poll, poll_interval
        self.concurrency = concurrency or (lambda provider: DEFAULT_CONCURRENCY)
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="aistudio-job")
        self._sems, self._lock, self._stop = {}, threading.Lock(), threading.Event()
        self._poller = None

    def _sem(self, provider):
        with self._lock:
            if provider not in self._sems:
                self._sems[provider] = threading.BoundedSemaphore(max(1, int(self.concurrency(provider) or DEFAULT_CONCURRENCY)))
            return self._sems[provider]

    def submit(self, project, kind, **kw):
        job = enqueue(self.root, project, kind, **kw)
        self.pool.submit(self._run, job["id"])
        return job

    def _run(self, jid):
        job = get(self.root, jid)
        if not job:
            return
        with self._sem(job["provider"] or "default"):
            if not claim(self.root, jid):
                return
            job = get(self.root, jid)

            def progress(pct):
                update(self.root, jid, progress=round(pct, 1))
                if get(self.root, jid)["cancel_requested"]:
                    raise Cancelled()
            try:
                res = self.handlers[job["kind"]](job, progress)
            except Cancelled:
                finish(self.root, jid, "cancelled", error="cancelled")
            except Exception as e:   # provider/network failure: record it, never crash the server
                extra = {"budget_diff": e.diff} if hasattr(e, "diff") else None
                finish(self.root, jid, "failed", result=extra, error=error_text(e))
            else:
                if get(self.root, jid)["cancel_requested"]:
                    finish(self.root, jid, "cancelled", result=res, error="cancelled while running; the work may already be done and billed")
                elif isinstance(res, dict) and res.get("pending") and res.get("job_id"):
                    update(self.root, jid, provider_job=res["job_id"])
                    finish(self.root, jid, "provider_pending", result=res)
                    self._start_poller()
                else:
                    finish(self.root, jid, "completed", result=res)

    # ---- provider polling (resumes through the existing sync path)
    def _start_poller(self):
        with self._lock:
            if self.poll and (self._poller is None or not self._poller.is_alive()):
                self._poller = threading.Thread(target=self._poll_loop, daemon=True, name="aistudio-job-poll")
                self._poller.start()

    def poll_once(self):
        pending = list_jobs(self.root, state="provider_pending")
        for job in pending:
            try:
                outcome = self.poll(job)
            except Exception:
                continue    # transient; try again next round
            if outcome and get(self.root, job["id"])["state"] == "provider_pending":
                finish(self.root, job["id"], outcome, error="" if outcome == "completed" else "the provider reported the job failed")
        return len(pending)

    def _poll_loop(self):
        while not self._stop.is_set() and self.poll_once():
            self._stop.wait(self.poll_interval)

    # ---- startup
    def reconcile(self):
        """Run once when the server starts (a single server owns the ledger).  Never re-runs paid work."""
        for job in list_jobs(self.root, limit=100000):
            free = job["kind"] in FREE_KINDS
            if job["state"] in ("queued", "running") and free:
                update(self.root, job["id"], state="queued")
                self.pool.submit(self._run, job["id"])
            elif job["state"] == "running":
                update(self.root, job["id"], state="needs_sync",
                       error="the server stopped while this was running; it may already have been billed. Check Costs, sync, then propose again if needed")
            elif job["state"] == "queued":
                update(self.root, job["id"], state="needs_sync",
                       error="the server stopped before this started; approvals do not carry over a restart. Propose again if you still want it")
        prune(self.root)
        self._start_poller()

    def shutdown(self):
        self._stop.set()
        self.pool.shutdown(wait=False, cancel_futures=True)


def make_poller(ws):
    """provider_pending -> outcome, using the existing sync flow (fetches the real status/cost and saves the clip)."""
    def poll(job):
        ws.sync(job["project"])
        for r in costlog.read_log(ws.pdir(job["project"])):
            if r.get("job_id") == job["provider_job"]:
                return None if r["result"] == "pending" else ("failed" if r["result"] == "failed" else "completed")
        return None
    return poll
