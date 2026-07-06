from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "automation.sqlite3"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS engine_info (
    id INTEGER PRIMARY KEY,
    engine_start_time TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS technician_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE IF NOT EXISTS technicians (
    nik VARCHAR PRIMARY KEY,
    name VARCHAR,
    email VARCHAR NOT NULL UNIQUE,
    group_id INTEGER NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    FOREIGN KEY (group_id) REFERENCES technician_groups(id)
);

CREATE TABLE IF NOT EXISTS service_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sdp_template_id VARCHAR NOT NULL UNIQUE,
    template_name VARCHAR NOT NULL UNIQUE,
    owning_group_id INTEGER NOT NULL,
    policy JSON NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT 1,
    FOREIGN KEY (owning_group_id) REFERENCES technician_groups(id)
);

CREATE TABLE IF NOT EXISTS ticket_jobs (
    ticket_id VARCHAR PRIMARY KEY,
    service_template_id INTEGER,
    status VARCHAR NOT NULL,
    resolution_time_seconds DECIMAL,
    input_token_count INTEGER DEFAULT 0,
    output_token_count INTEGER DEFAULT 0,
    planner_input_token_count INTEGER DEFAULT 0,
    planner_output_token_count INTEGER DEFAULT 0,
    executor_input_token_count INTEGER DEFAULT 0,
    executor_output_token_count INTEGER DEFAULT 0,
    sdp_resolution_status VARCHAR,
    sdp_resolution_comment TEXT,
    sdp_resolution_response JSON,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    FOREIGN KEY (service_template_id) REFERENCES service_templates(id)
);

CREATE TABLE IF NOT EXISTS ticket_payloads (
    ticket_id VARCHAR PRIMARY KEY,
    raw_ticket JSON NOT NULL,
    normalized_input JSON,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    FOREIGN KEY (ticket_id) REFERENCES ticket_jobs(ticket_id)
);
"""

TICKET_JOB_EXTRA_COLUMNS: dict[str, str] = {
    "planner_input_token_count": "INTEGER DEFAULT 0",
    "planner_output_token_count": "INTEGER DEFAULT 0",
    "executor_input_token_count": "INTEGER DEFAULT 0",
    "executor_output_token_count": "INTEGER DEFAULT 0",
    "sdp_resolution_status": "VARCHAR",
    "sdp_resolution_comment": "TEXT",
    "sdp_resolution_response": "JSON",
}

TICKET_JOB_COLUMNS = [
    "ticket_id",
    "service_template_id",
    "status",
    "resolution_time_seconds",
    "input_token_count",
    "output_token_count",
    "planner_input_token_count",
    "planner_output_token_count",
    "executor_input_token_count",
    "executor_output_token_count",
    "sdp_resolution_status",
    "sdp_resolution_comment",
    "sdp_resolution_response",
    "created_at",
    "updated_at",
]


def now_ms() -> int:
    return int(time.time() * 1000)


def now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def timestamp_to_ms(value: str | None) -> int | None:
    if not value:
        return None

    normalized = str(value).strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return int(parsed.timestamp() * 1000)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def _int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_columns(conn: sqlite3.Connection, table_name: str, columns: dict[str, str]) -> None:
    existing = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})")}
    for column_name, column_def in columns.items():
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")


def init_db(db_path: Path | str = DB_PATH) -> None:
    """Create or migrate the database schema. This function does not seed data."""
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        _ensure_columns(conn, "ticket_jobs", TICKET_JOB_EXTRA_COLUMNS)


def reset_db(db_path: Path | str = DB_PATH) -> None:
    """Delete the current SQLite DB file and recreate the empty schema."""
    path = Path(db_path)
    if path.exists():
        path.unlink()
    init_db(path)


def ensure_engine_started_at_ms(db_path: Path | str = DB_PATH) -> int:
    """
    Return the engine startup watermark as epoch milliseconds.

    The DB stores engine_info.engine_start_time as an ISO timestamp. SDP's
    created_time.value uses epoch milliseconds, so this helper converts it.
    """
    init_db(db_path)

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT engine_start_time FROM engine_info WHERE id = 1"
        ).fetchone()

        if row:
            stored_ms = timestamp_to_ms(row["engine_start_time"])
            if stored_ms is not None:
                return stored_ms

        timestamp = now_timestamp()
        conn.execute(
            "INSERT INTO engine_info (id, engine_start_time) VALUES (1, ?)",
            (timestamp,),
        )
        return timestamp_to_ms(timestamp) or now_ms()


def reset_engine_started_at_ms(db_path: Path | str = DB_PATH) -> int:
    """Reset engine_info.engine_start_time to now and return epoch milliseconds."""
    init_db(db_path)
    timestamp = now_timestamp()

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO engine_info (id, engine_start_time)
            VALUES (1, ?)
            ON CONFLICT(id) DO UPDATE SET
                engine_start_time = excluded.engine_start_time
            """,
            (timestamp,),
        )

    return timestamp_to_ms(timestamp) or now_ms()


def get_engine_info(db_path: Path | str = DB_PATH) -> dict[str, Any] | None:
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, engine_start_time FROM engine_info WHERE id = 1"
        ).fetchone()
    return dict(row) if row else None


def upsert_technician_group(
    *,
    name: str,
    description: str | None = None,
    db_path: Path | str = DB_PATH,
) -> int:
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO technician_groups (name, description)
            VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET
                description = excluded.description
            """,
            (name, description),
        )
        row = conn.execute(
            "SELECT id FROM technician_groups WHERE name = ?",
            (name,),
        ).fetchone()
    return int(row["id"])


def list_technician_groups(db_path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, name, description FROM technician_groups ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_technician(
    *,
    nik: str,
    email: str,
    group_id: int,
    name: str | None = None,
    is_active: bool = True,
    db_path: Path | str = DB_PATH,
) -> None:
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO technicians (nik, name, email, group_id, is_active)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(nik) DO UPDATE SET
                name = excluded.name,
                email = excluded.email,
                group_id = excluded.group_id,
                is_active = excluded.is_active
            """,
            (nik, name, email, int(group_id), int(bool(is_active))),
        )


def upsert_service_template(
    *,
    sdp_template_id: str,
    template_name: str,
    owning_group_id: int,
    policy: dict[str, Any],
    is_enabled: bool = True,
    db_path: Path | str = DB_PATH,
) -> int:
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO service_templates (
                sdp_template_id,
                template_name,
                owning_group_id,
                policy,
                is_enabled
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(sdp_template_id) DO UPDATE SET
                template_name = excluded.template_name,
                owning_group_id = excluded.owning_group_id,
                policy = excluded.policy,
                is_enabled = excluded.is_enabled
            """,
            (
                str(sdp_template_id),
                template_name,
                int(owning_group_id),
                _json_dumps(policy),
                int(bool(is_enabled)),
            ),
        )
        row = conn.execute(
            "SELECT id FROM service_templates WHERE sdp_template_id = ?",
            (str(sdp_template_id),),
        ).fetchone()
    return int(row["id"])


def get_service_template_by_template_name(
    template_name: str,
    db_path: Path | str = DB_PATH,
) -> dict[str, Any] | None:
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, sdp_template_id, template_name, owning_group_id, policy, is_enabled
            FROM service_templates
            WHERE template_name = ? AND is_enabled = 1
            """,
            (template_name,),
        ).fetchone()

    if row is None:
        return None

    result = dict(row)
    result["policy"] = _json_loads(result["policy"])
    result["is_enabled"] = bool(result["is_enabled"])
    return result


def get_service_template_by_id(
    service_template_id: int,
    db_path: Path | str = DB_PATH,
) -> dict[str, Any] | None:
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, sdp_template_id, template_name, owning_group_id, policy, is_enabled
            FROM service_templates
            WHERE id = ?
            """,
            (int(service_template_id),),
        ).fetchone()

    if row is None:
        return None

    result = dict(row)
    result["policy"] = _json_loads(result["policy"])
    result["is_enabled"] = bool(result["is_enabled"])
    return result


def list_service_templates(db_path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, sdp_template_id, template_name, owning_group_id, policy, is_enabled
            FROM service_templates
            ORDER BY id
            """
        ).fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["policy"] = _json_loads(item["policy"])
        item["is_enabled"] = bool(item["is_enabled"])
        result.append(item)
    return result


def upsert_ticket_job(
    ticket_id: str,
    status: str = "received",
    *,
    service_template_id: int | None = None,
    input_token_count: int = 0,
    output_token_count: int = 0,
    planner_input_token_count: int = 0,
    planner_output_token_count: int = 0,
    executor_input_token_count: int = 0,
    executor_output_token_count: int = 0,
    db_path: Path | str = DB_PATH,
) -> None:
    """
    Insert a ticket job if it is new.

    Existing tickets are left untouched so polling the same SDP ticket twice
    does not reset its status, metrics, or resolution time.
    """
    init_db(db_path)
    timestamp = now_timestamp()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO ticket_jobs (
                ticket_id,
                service_template_id,
                status,
                resolution_time_seconds,
                input_token_count,
                output_token_count,
                planner_input_token_count,
                planner_output_token_count,
                executor_input_token_count,
                executor_output_token_count,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticket_id) DO NOTHING
            """,
            (
                str(ticket_id),
                service_template_id,
                status,
                int(input_token_count),
                int(output_token_count),
                int(planner_input_token_count),
                int(planner_output_token_count),
                int(executor_input_token_count),
                int(executor_output_token_count),
                timestamp,
                timestamp,
            ),
        )


def update_ticket_status(
    ticket_id: str,
    status: str,
    db_path: Path | str = DB_PATH,
) -> None:
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE ticket_jobs
            SET status = ?,
                updated_at = ?
            WHERE ticket_id = ?
            """,
            (status, now_timestamp(), str(ticket_id)),
        )


def update_ticket_token_usage(
    ticket_id: str,
    token_usage: dict[str, Any],
    db_path: Path | str = DB_PATH,
) -> None:
    """Persist planner, executor, and aggregate token usage for one ticket job."""
    init_db(db_path)
    planner = token_usage.get("planner") if isinstance(token_usage.get("planner"), dict) else {}
    executor = token_usage.get("executor") if isinstance(token_usage.get("executor"), dict) else {}
    total = token_usage.get("total") if isinstance(token_usage.get("total"), dict) else {}

    planner_input = _int_or_zero(planner.get("input_token_count"))
    planner_output = _int_or_zero(planner.get("output_token_count"))
    executor_input = _int_or_zero(executor.get("input_token_count"))
    executor_output = _int_or_zero(executor.get("output_token_count"))

    total_input = _int_or_zero(total.get("input_token_count")) or planner_input + executor_input
    total_output = _int_or_zero(total.get("output_token_count")) or planner_output + executor_output

    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE ticket_jobs
            SET input_token_count = ?,
                output_token_count = ?,
                planner_input_token_count = ?,
                planner_output_token_count = ?,
                executor_input_token_count = ?,
                executor_output_token_count = ?,
                updated_at = ?
            WHERE ticket_id = ?
            """,
            (
                total_input,
                total_output,
                planner_input,
                planner_output,
                executor_input,
                executor_output,
                now_timestamp(),
                str(ticket_id),
            ),
        )


def finish_ticket_job(
    ticket_id: str,
    status: str,
    resolution_time_seconds: float,
    *,
    input_token_count: int | None = None,
    output_token_count: int | None = None,
    db_path: Path | str = DB_PATH,
) -> None:
    init_db(db_path)
    with get_connection(db_path) as conn:
        current = conn.execute(
            """
            SELECT input_token_count, output_token_count
            FROM ticket_jobs
            WHERE ticket_id = ?
            """,
            (str(ticket_id),),
        ).fetchone()

        current_input = int(current["input_token_count"] or 0) if current else 0
        current_output = int(current["output_token_count"] or 0) if current else 0

        conn.execute(
            """
            UPDATE ticket_jobs
            SET status = ?,
                resolution_time_seconds = ?,
                input_token_count = ?,
                output_token_count = ?,
                updated_at = ?
            WHERE ticket_id = ?
            """,
            (
                status,
                float(resolution_time_seconds),
                current_input if input_token_count is None else int(input_token_count),
                current_output if output_token_count is None else int(output_token_count),
                now_timestamp(),
                str(ticket_id),
            ),
        )


def update_ticket_sdp_resolution(
    ticket_id: str,
    *,
    sdp_resolution_status: str,
    resolution_comment: str | None = None,
    sdp_response: dict[str, Any] | None = None,
    db_path: Path | str = DB_PATH,
) -> None:
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE ticket_jobs
            SET sdp_resolution_status = ?,
                sdp_resolution_comment = ?,
                sdp_resolution_response = ?,
                updated_at = ?
            WHERE ticket_id = ?
            """,
            (
                sdp_resolution_status,
                resolution_comment,
                _json_dumps(sdp_response) if sdp_response is not None else None,
                now_timestamp(),
                str(ticket_id),
            ),
        )


def upsert_ticket_payload(
    ticket_id: str,
    raw_ticket: dict[str, Any],
    *,
    normalized_input: dict[str, Any] | None = None,
    db_path: Path | str = DB_PATH,
) -> None:
    init_db(db_path)
    timestamp = now_timestamp()

    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT normalized_input FROM ticket_payloads WHERE ticket_id = ?",
            (str(ticket_id),),
        ).fetchone()
        normalized_json = (
            _json_dumps(normalized_input)
            if normalized_input is not None
            else (existing["normalized_input"] if existing else None)
        )

        conn.execute(
            """
            INSERT INTO ticket_payloads (
                ticket_id,
                raw_ticket,
                normalized_input,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(ticket_id) DO UPDATE SET
                raw_ticket = excluded.raw_ticket,
                normalized_input = excluded.normalized_input,
                updated_at = excluded.updated_at
            """,
            (
                str(ticket_id),
                _json_dumps(raw_ticket),
                normalized_json,
                timestamp,
                timestamp,
            ),
        )


def update_ticket_normalized_input(
    ticket_id: str,
    normalized_input: dict[str, Any],
    db_path: Path | str = DB_PATH,
) -> None:
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE ticket_payloads
            SET normalized_input = ?,
                updated_at = ?
            WHERE ticket_id = ?
            """,
            (_json_dumps(normalized_input), now_timestamp(), str(ticket_id)),
        )


def _ticket_job_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    result["sdp_resolution_response"] = _json_loads(result.get("sdp_resolution_response"))
    return result


def get_ticket_job(
    ticket_id: str,
    db_path: Path | str = DB_PATH,
) -> dict[str, Any] | None:
    init_db(db_path)
    select_columns = ",\n                ".join(TICKET_JOB_COLUMNS)
    with get_connection(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT
                {select_columns}
            FROM ticket_jobs
            WHERE ticket_id = ?
            """,
            (str(ticket_id),),
        ).fetchone()

    return _ticket_job_from_row(row)


def get_ticket_payload(
    ticket_id: str,
    db_path: Path | str = DB_PATH,
) -> dict[str, Any] | None:
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT ticket_id, raw_ticket, normalized_input, created_at, updated_at
            FROM ticket_payloads
            WHERE ticket_id = ?
            """,
            (str(ticket_id),),
        ).fetchone()

    if row is None:
        return None

    result = dict(row)
    result["raw_ticket"] = _json_loads(result["raw_ticket"])
    result["normalized_input"] = _json_loads(result["normalized_input"])
    return result


def list_ticket_jobs(db_path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    init_db(db_path)
    select_columns = ",\n                ".join(TICKET_JOB_COLUMNS)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                {select_columns}
            FROM ticket_jobs
            ORDER BY ticket_id
            """
        ).fetchall()

    return [_ticket_job_from_row(row) or {} for row in rows]


def list_ticket_payloads(db_path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT ticket_id, raw_ticket, normalized_input, created_at, updated_at
            FROM ticket_payloads
            ORDER BY ticket_id
            """
        ).fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["raw_ticket"] = _json_loads(item["raw_ticket"])
        item["normalized_input"] = _json_loads(item["normalized_input"])
        result.append(item)
    return result


def set_service_template_enabled(
    identifier: str | int,
    enabled: bool,
    db_path: Path | str = DB_PATH,
) -> int:
    """Enable/disable a service template by DB id, SDP template id, or template name."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE service_templates
            SET is_enabled = ?
            WHERE id = ? OR sdp_template_id = ? OR template_name = ?
            """,
            (int(bool(enabled)), str(identifier), str(identifier), str(identifier)),
        )
        return int(cursor.rowcount)


def delete_service_template(
    identifier: str | int,
    db_path: Path | str = DB_PATH,
) -> int:
    """Delete a service template by DB id, SDP template id, or template name."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            DELETE FROM service_templates
            WHERE id = ? OR sdp_template_id = ? OR template_name = ?
            """,
            (str(identifier), str(identifier), str(identifier)),
        )
        return int(cursor.rowcount)
