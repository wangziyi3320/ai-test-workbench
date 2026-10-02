"""小型单用户演示版的 SQLite 持久化层。"""

from contextlib import contextmanager
from pathlib import Path
import sqlite3


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS requirements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('requirement', 'openapi')),
    content TEXT NOT NULL,
    source_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS test_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requirement_id INTEGER NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    category TEXT NOT NULL CHECK(category IN ('normal', 'boundary', 'exception', 'security')),
    priority TEXT NOT NULL CHECK(priority IN ('P0', 'P1', 'P2')),
    preconditions TEXT NOT NULL DEFAULT '',
    steps TEXT NOT NULL DEFAULT '',
    expected TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'draft' CHECK(review_status IN ('draft', 'approved', 'rejected')),
    method TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    expected_http_status INTEGER,
    generator TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS defects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requirement_id INTEGER NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    test_case_id INTEGER REFERENCES test_cases(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('critical', 'major', 'minor')),
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'fixed', 'verified', 'closed')),
    steps TEXT NOT NULL,
    expected TEXT NOT NULL,
    actual TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS generation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requirement_id INTEGER NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    generator TEXT NOT NULL,
    case_count INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS test_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requirement_id INTEGER NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    test_case_id INTEGER NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
    base_url TEXT NOT NULL,
    request_url TEXT NOT NULL,
    expected_status INTEGER NOT NULL,
    actual_status INTEGER,
    passed INTEGER NOT NULL CHECK(passed IN (0, 1)),
    latency_ms REAL NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    executed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_cases_requirement ON test_cases(requirement_id);
CREATE INDEX IF NOT EXISTS idx_defects_requirement ON defects(requirement_id);
CREATE INDEX IF NOT EXISTS idx_runs_requirement ON test_runs(requirement_id);
"""


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def connection(path: Path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None
