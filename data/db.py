"""
Day 2a: SQLite storage for order-book snapshots.

One file-based database (no server) with one table, book_snapshots, holding a
flat numeric row per (token, poll time) as produced by check_book.snapshot().
This is the simplest thing that logs snapshots continuously and lets the Day-3
model and Day-6 dashboard query price history back out.

  init_db()          — create the table + index (safe to call repeatedly)
  insert_snapshot(s) — persist one snapshot dict
  get_conn()         — the shared, reused connection (opened once)
  close()            — close the shared connection (e.g. on shutdown)
  connect()          — a NEW standalone connection (ad-hoc queries / tests)

Run: python data/db.py   # just initializes the database file
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "polypredict.db"

# The schema (blueprint): what the table looks like, not the data itself.
# token_id is TEXT because the ids are ~77-digit numbers, far beyond SQLite's
# 64-bit INTEGER — storing them as numbers would corrupt them. Prices/sizes are
# REAL (float). captured_at is ISO-8601 UTC text (SQLite has no datetime type;
# ISO text sorts chronologically). The index makes "this token over time"
# queries — the ones the model and dashboard run — fast.
SCHEMA = """
CREATE TABLE IF NOT EXISTS book_snapshots (
    id          INTEGER PRIMARY KEY,
    token_id    TEXT    NOT NULL,
    captured_at TEXT    NOT NULL,
    best_bid    REAL,
    best_ask    REAL,
    bid_size    REAL,
    ask_size    REAL,
    midpoint    REAL
);
CREATE INDEX IF NOT EXISTS idx_snap_token_time
    ON book_snapshots (token_id, captured_at);
"""


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Open a NEW standalone connection (rows accessible by column name).
    Use for ad-hoc queries or tests that want their own isolated connection."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    """Return the shared connection to the default DB, opening it once.

    The poller inserts every round; reopening a connection per write is
    wasteful, so we keep one open for the process's lifetime (same idea as the
    reused ClobClient). WAL mode lets a reader (the Day-6 dashboard) and the
    writing poller work at the same time without blocking each other.

    Single-threaded use only — sqlite3 connections aren't shared across threads.
    """
    global _conn
    if _conn is None:
        _conn = connect()
        _conn.execute("PRAGMA journal_mode=WAL")
    return _conn


def close() -> None:
    """Close the shared connection if it's open (e.g. on poller shutdown)."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def init_db(conn: sqlite3.Connection | None = None) -> None:
    """Create the table + index if they don't already exist. Idempotent.
    Defaults to the shared connection; pass conn to target another (tests)."""
    conn = conn or get_conn()
    with conn:  # commit on success / rollback on error (does NOT close)
        conn.executescript(SCHEMA)


def insert_snapshot(snap: dict, conn: sqlite3.Connection | None = None) -> None:
    """Persist one snapshot dict (the shape returned by check_book.snapshot())."""
    conn = conn or get_conn()
    with conn:
        conn.execute(
            """
            INSERT INTO book_snapshots
                (token_id, captured_at, best_bid, best_ask,
                 bid_size, ask_size, midpoint)
            VALUES
                (:token_id, :captured_at, :best_bid, :best_ask,
                 :bid_size, :ask_size, :midpoint)
            """,
            snap,
        )


if __name__ == "__main__":
    init_db()
    print(f"Initialized {DB_PATH}")
