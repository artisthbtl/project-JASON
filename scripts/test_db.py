import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db import (
    ensure_engine_started_at_ms,
    finish_ticket_job,
    get_ticket_job,
    init_db,
    upsert_ticket_job,
    update_ticket_status,
)


def main():
    init_db()
    print("engine_started_at_ms:", ensure_engine_started_at_ms())

    ticket_id = "443123"
    upsert_ticket_job(ticket_id, "received")
    update_ticket_status(ticket_id, "running")
    finish_ticket_job(ticket_id, "resolved", 12.34)

    print(get_ticket_job(ticket_id))


if __name__ == "__main__":
    main()
