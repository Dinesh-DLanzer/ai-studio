"""The only module that talks SQL.  Everything durable that is not a project file (the job ledger now, the library later) goes through
execute / query / transaction, so a hosted tier can swap this file for Postgres.  Plain SQL with ? placeholders; no sqlite-only features
outside this file.  Every row carries tenant_id and actor ('local' in single-user mode).

Safe across threads (one connection per thread) and processes (WAL, busy_timeout, short IMMEDIATE transactions).
"""
import contextlib
import sqlite3
import threading
import time
from pathlib import Path

TENANT = "local"
ACTOR = "local"

# MIGRATIONS[i] brings the database from user_version i to i+1.  Append only; never edit a shipped entry.
MIGRATIONS = [
    """
    CREATE TABLE jobs (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL DEFAULT 'local', actor TEXT NOT NULL DEFAULT 'local',
        project TEXT NOT NULL, kind TEXT NOT NULL, target TEXT NOT NULL DEFAULT '', proposal_id TEXT NOT NULL DEFAULT '',
        batch_id TEXT NOT NULL DEFAULT '', state TEXT NOT NULL, provider TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
        provider_job TEXT NOT NULL DEFAULT '', progress REAL NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
        created REAL NOT NULL, updated REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL DEFAULT '{}',
        result TEXT NOT NULL DEFAULT '', cancel_requested INTEGER NOT NULL DEFAULT 0);
    CREATE INDEX jobs_project ON jobs (tenant_id, project, created);
    CREATE INDEX jobs_state ON jobs (state);
    """,
    """
    CREATE TABLE items (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL DEFAULT 'local', actor TEXT NOT NULL DEFAULT 'local',
        project TEXT NOT NULL, kind TEXT NOT NULL, category TEXT NOT NULL DEFAULT '', file TEXT NOT NULL,
        sha TEXT NOT NULL DEFAULT '', prompt TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
        provider TEXT NOT NULL DEFAULT '', seed TEXT NOT NULL DEFAULT '', params TEXT NOT NULL DEFAULT '{}',
        cost REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'completed', favorite INTEGER NOT NULL DEFAULT 0,
        created REAL NOT NULL DEFAULT 0, meta TEXT NOT NULL DEFAULT '{}');
    CREATE UNIQUE INDEX items_identity ON items (tenant_id, actor, project, file, sha);
    CREATE INDEX items_project ON items (tenant_id, project, created);
    CREATE INDEX items_filters ON items (tenant_id, kind, model, status, favorite, created, cost);
    """,
]

_local = threading.local()
_init_lock = threading.Lock()


def db_path(root):
    return Path(root) / "state" / "aistudio.db"


def _migrate(con):
    # take the write lock first: a second process waits here, then sees the new user_version and does nothing.
    con.execute("BEGIN IMMEDIATE")
    try:
        version = con.execute("PRAGMA user_version").fetchone()[0]
        for i in range(version, len(MIGRATIONS)):
            for stmt in MIGRATIONS[i].split(";"):
                if stmt.strip():
                    con.execute(stmt)
            con.execute(f"PRAGMA user_version = {i + 1}")   # PRAGMA cannot take parameters; i is ours
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise


def connect(root):
    """This thread's connection to <root>/state/aistudio.db (created and migrated on first use)."""
    path = db_path(root)
    cons = getattr(_local, "cons", None)
    if cons is None:
        cons = _local.cons = {}
    con = cons.get(str(path))
    if con is not None and not path.exists():   # workspace was deleted under us (tests)
        con.close()
        con = None
    if con is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(path), timeout=30, isolation_level=None)   # autocommit; transaction() opens explicit ones
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout = 30000")
        con.execute("PRAGMA synchronous = NORMAL")
        with _init_lock:
            for attempt in range(100):   # switching to WAL can fail at once with "locked" while another process starts up
                try:
                    con.execute("PRAGMA journal_mode = WAL")
                    _migrate(con)
                    break
                except sqlite3.OperationalError:
                    if attempt == 99:
                        raise
                    time.sleep(0.05)
        cons[str(path)] = con
    return con


def close_all():
    """Close this thread's connections."""
    for con in getattr(_local, "cons", {}).values():
        con.close()
    _local.cons = {}


def execute(root, sql, params=()):
    """Run one write statement in its own short transaction; returns the number of rows changed."""
    with transaction(root) as tx:
        return tx.execute(sql, params)


def query(root, sql, params=()):
    return [dict(r) for r in connect(root).execute(sql, params).fetchall()]


class _Tx:
    def __init__(self, con):
        self.con = con

    def execute(self, sql, params=()):
        return self.con.execute(sql, params).rowcount

    def query(self, sql, params=()):
        return [dict(r) for r in self.con.execute(sql, params).fetchall()]


@contextlib.contextmanager
def transaction(root):
    """BEGIN IMMEDIATE ... COMMIT: takes the write lock up front, so two processes queue instead of failing half way."""
    con = connect(root)
    con.execute("BEGIN IMMEDIATE")
    try:
        yield _Tx(con)
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
