from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "automation.sqlite3"


def now_ms() -> int:
    """Return current Unix time in milliseconds."""
    return int(time.time() * 1000)


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Create a SQLite connection with dict-like rows and foreign keys enabled."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | str = DB_PATH) -> None:
    """Create the minimal database schema if it does not already exist."""
    with get_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sdp_poll_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                engine_started_at_ms INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ticket_jobs (
                ticket_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                resolution_time REAL
            );
            """
        )


def ensure_engine_started_at_ms(db_path: Path | str = DB_PATH) -> int:
    """
    Return the engine startup watermark.

    If it does not exist yet, create it using the current time. This makes the
    poller ignore tickets created before the engine was first initialized.
    """
    init_db(db_path)

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT engine_started_at_ms FROM sdp_poll_state WHERE id = 1"
        ).fetchone()

        if row:
            return int(row["engine_started_at_ms"])

        started_at = now_ms()
        conn.execute(
            "INSERT INTO sdp_poll_state (id, engine_started_at_ms) VALUES (1, ?)",
            (started_at,),
        )
        return started_at


def reset_engine_started_at_ms(db_path: Path | str = DB_PATH) -> int:
    """
    Reset the startup watermark to now.

    Use this when you intentionally want the engine to start from a fresh point
    and ignore all older SDP tickets.
    """
    init_db(db_path)
    started_at = now_ms()

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sdp_poll_state (id, engine_started_at_ms)
            VALUES (1, ?)
            ON CONFLICT(id) DO UPDATE SET
                engine_started_at_ms = excluded.engine_started_at_ms
            """,
            (started_at,),
        )

    return started_at


def upsert_ticket_job(
    ticket_id: str,
    status: str = "received",
    db_path: Path | str = DB_PATH,
) -> None:
    """
    Insert a ticket job if it is new.

    Existing tickets are left untouched so polling the same SDP ticket twice
    does not reset its status or resolution time.
    """
    init_db(db_path)

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO ticket_jobs (ticket_id, status, resolution_time)
            VALUES (?, ?, NULL)
            ON CONFLICT(ticket_id) DO NOTHING
            """,
            (str(ticket_id), status),
        )


def update_ticket_status(
    ticket_id: str,
    status: str,
    db_path: Path | str = DB_PATH,
) -> None:
    """Update only the ticket status."""
    init_db(db_path)

    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE ticket_jobs
            SET status = ?
            WHERE ticket_id = ?
            """,
            (status, str(ticket_id)),
        )


def finish_ticket_job(
    ticket_id: str,
    status: str,
    resolution_time_seconds: float,
    db_path: Path | str = DB_PATH,
) -> None:
    """Mark a ticket as finished and store workflow duration in seconds."""
    init_db(db_path)

    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE ticket_jobs
            SET status = ?,
                resolution_time = ?
            WHERE ticket_id = ?
            """,
            (status, float(resolution_time_seconds), str(ticket_id)),
        )


def get_ticket_job(
    ticket_id: str,
    db_path: Path | str = DB_PATH,
) -> dict[str, Any] | None:
    """Fetch one ticket job as a normal dict."""
    init_db(db_path)

    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT ticket_id, status, resolution_time
            FROM ticket_jobs
            WHERE ticket_id = ?
            """,
            (str(ticket_id),),
        ).fetchone()

    return dict(row) if row else None


def list_ticket_jobs(db_path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    """Fetch all ticket jobs for quick debugging."""
    init_db(db_path)

    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT ticket_id, status, resolution_time
            FROM ticket_jobs
            ORDER BY ticket_id
            """
        ).fetchall()

    return [dict(row) for row in rows]
