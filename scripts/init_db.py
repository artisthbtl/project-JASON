import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db import DB_PATH, ensure_engine_started_at_ms, init_db, list_ticket_jobs


def main():
    init_db()
    engine_started_at_ms = ensure_engine_started_at_ms()

    print(f"SQLite DB path: {DB_PATH}")
    print(f"engine_started_at_ms: {engine_started_at_ms}")
    print(f"ticket_jobs: {list_ticket_jobs()}")


if __name__ == "__main__":
    main()
