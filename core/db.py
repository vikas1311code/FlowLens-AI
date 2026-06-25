"""
core/db.py
Lightweight SQLite persistence for run history.

No ORM, no migrations framework — each run is stored as one row with the
whole run dict serialized as a JSON blob, plus a few plain columns (url,
status, created_at) that are indexed so the history / trends views don't
need to deserialize every row just to filter or sort.

This is intentionally simple: a QA tool's run history is read far more
than it's written, and the data shape will keep changing as features are
added, so a flexible JSON blob beats a rigid schema here.
"""
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent.parent / "outputs" / "db" / "runs.sqlite3"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Fields that must never be written to disk, no matter what's in the run dict.
_SECRET_KEYS = {"login_password"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id     TEXT PRIMARY KEY,
    url        TEXT NOT NULL,
    status     TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    data       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_url     ON runs(url);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at);

CREATE TABLE IF NOT EXISTS logs (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id  TEXT NOT NULL,
    ts      REAL NOT NULL,
    level   TEXT NOT NULL,
    msg     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_run ON logs(run_id, id);
"""


@contextmanager
def _conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    # WAL mode lets one process write while others read without "database is
    # locked" errors — this matters now that validation runs execute in their
    # own subprocess, writing progress while the API process reads it.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _conn() as c:
        c.executescript(_SCHEMA)


def _strip_secrets(run: dict) -> dict:
    return {k: v for k, v in run.items() if k not in _SECRET_KEYS}


def save_run(run: dict):
    """Insert or update a run's row. Safe to call repeatedly as a run progresses."""
    safe = _strip_secrets(run)
    now = time.time()
    blob = json.dumps(safe, default=str)
    with _conn() as c:
        c.execute(
            """
            INSERT INTO runs (run_id, url, status, created_at, updated_at, data)
            VALUES (:run_id, :url, :status, :created_at, :updated_at, :data)
            ON CONFLICT(run_id) DO UPDATE SET
                status=:status, updated_at=:updated_at, data=:data
            """,
            {
                "run_id": safe["run_id"],
                "url": safe.get("url", ""),
                "status": safe.get("status", "queued"),
                "created_at": safe.get("created_at", now),
                "updated_at": now,
                "data": blob,
            },
        )


def load_all_runs() -> dict:
    """Returns {run_id: run_dict} for every stored run, oldest first."""
    with _conn() as c:
        rows = c.execute("SELECT data FROM runs ORDER BY created_at ASC").fetchall()
    out = {}
    for r in rows:
        d = json.loads(r["data"])
        out[d["run_id"]] = d
    return out


def load_run(run_id: str) -> Optional[dict]:
    """Fresh read of a single run — used by the API process to see progress
    a worker subprocess has written, since that worker has its own memory
    and can't update this process's state directly."""
    with _conn() as c:
        row = c.execute("SELECT data FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return json.loads(row["data"]) if row else None


def count_active_runs() -> int:
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) as n FROM runs WHERE status IN ('queued', 'running')"
        ).fetchone()
    return row["n"]


def mark_status(run_id: str, status: str, error: Optional[str] = None, url: str = ""):
    """Quick status-only update — used for e.g. marking a run 'cancelled'
    without needing the full run dict on hand. Creates a minimal record if
    one doesn't exist yet (e.g. cancelled before the worker's first write)."""
    run = load_run(run_id) or {"run_id": run_id, "url": url, "created_at": time.time()}
    run["status"] = status
    if error:
        run["error"] = error
    save_run(run)


def append_log(run_id: str, level: str, msg: str):
    if not msg:
        return
    with _conn() as c:
        c.execute(
            "INSERT INTO logs (run_id, ts, level, msg) VALUES (?, ?, ?, ?)",
            (run_id, time.time(), level, msg),
        )


def load_logs_since(run_id: str, after_id: int = 0) -> list:
    """Log rows for a run with id > after_id, so a poller can ask for only
    what's new. Returns [{id, ts, level, msg}, ...]."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, ts, level, msg FROM logs WHERE run_id = ? AND id > ? ORDER BY id ASC",
            (run_id, after_id),
        ).fetchall()
    return [{"id": r["id"], "ts": r["ts"], "level": r["level"], "msg": r["msg"]} for r in rows]


def delete_logs(run_id: str):
    with _conn() as c:
        c.execute("DELETE FROM logs WHERE run_id = ?", (run_id,))


def load_runs_for_url(url: str, only_complete: bool = True) -> list:
    """Past runs against the same URL, oldest first — used for trend charts."""
    q = "SELECT data FROM runs WHERE url = ?"
    params = [url]
    if only_complete:
        q += " AND status = 'complete'"
    q += " ORDER BY created_at ASC"
    with _conn() as c:
        rows = c.execute(q, params).fetchall()
    return [json.loads(r["data"]) for r in rows]


def distinct_urls() -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT url, COUNT(*) as n, MAX(created_at) as last_run "
            "FROM runs WHERE status='complete' GROUP BY url ORDER BY last_run DESC"
        ).fetchall()
    return [{"url": r["url"], "run_count": r["n"], "last_run": r["last_run"]} for r in rows]


def delete_run(run_id: str):
    with _conn() as c:
        c.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))