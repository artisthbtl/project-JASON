from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import get_int_env, load_project_env  # noqa: E402
from src.db import (  # noqa: E402
    ensure_engine_started_at_ms,
    init_db,
    reset_engine_started_at_ms,
)
from src.engine import EngineRunOptions, TicketAutomationEngine, log  # noqa: E402
from src.sdp_client import ServiceDeskPlusClient  # noqa: E402

DEFAULT_INTERVAL_SECONDS = 60
DEFAULT_ROW_COUNT = 100


def parse_args() -> argparse.Namespace:
    load_project_env(override=True)

    default_interval = get_int_env("SDP_POLL_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)
    default_row_count = get_int_env("SDP_ROW_COUNT", DEFAULT_ROW_COUNT)
    default_template = os.getenv("SDP_TARGET_TEMPLATE_NAME") or None

    parser = argparse.ArgumentParser(
        description=(
            "Central ServiceDeskPlus ticket automation runner: poll SDP, parse the "
            "description table, build agent input, optionally run the workflow, and print output."
        )
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=default_interval,
        help="Polling interval in seconds. Default: SDP_POLL_INTERVAL_SECONDS or 60.",
    )
    parser.add_argument(
        "--row-count",
        type=int,
        default=default_row_count,
        help="SDP page size. Default: SDP_ROW_COUNT or 100.",
    )
    parser.add_argument(
        "--template",
        default=default_template,
        help=(
            "Optional exact SDP template name to allow. The template must still be "
            "registered and enabled in service_templates."
        ),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one polling cycle and exit.",
    )
    parser.add_argument(
        "--resume-watermark",
        action="store_true",
        help="Use the existing engine_start_time instead of resetting it on engine start.",
    )
    parser.add_argument(
        "--no-print-final-input",
        action="store_true",
        help="Do not print final AI input for queued tickets.",
    )
    parser.add_argument(
        "--run-workflow",
        action="store_true",
        help=(
            "Invoke the LangGraph agent workflow for queued tickets. Without this flag, "
            "the runner stops after queueing and printing the final AI input."
        ),
    )
    parser.add_argument(
        "--resolve-sdp-ticket",
        action="store_true",
        help=(
            "After a successful approved workflow execution, add the execution resolution "
            "to SDP and update the request status. Requires --run-workflow."
        ),
    )
    parser.add_argument(
        "--sdp-resolved-status-name",
        default=os.getenv("SDP_RESOLVED_STATUS_NAME", "Resolved"),
        help="SDP status name used by --resolve-sdp-ticket. Default: Resolved.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce node-level progress logs.",
    )
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()
    init_db()

    if args.resolve_sdp_ticket and not args.run_workflow:
        raise SystemExit("--resolve-sdp-ticket requires --run-workflow.")

    if args.resume_watermark:
        engine_started_at_ms = ensure_engine_started_at_ms()
        log(f"Using existing engine_started_at_ms={engine_started_at_ms}")
    else:
        engine_started_at_ms = reset_engine_started_at_ms()
        log(f"Reset engine_started_at_ms={engine_started_at_ms}")

    client = ServiceDeskPlusClient.from_env()
    engine = TicketAutomationEngine(client)
    options = EngineRunOptions(
        row_count=args.row_count,
        target_template_name=args.template,
        print_final_input=not args.no_print_final_input,
        run_workflow=args.run_workflow,
        resolve_sdp_ticket=args.resolve_sdp_ticket,
        sdp_resolved_status_name=args.sdp_resolved_status_name,
        verbose=not args.quiet,
    )

    template_msg = args.template if args.template else "enabled service_templates"
    mode_msg = "workflow execution enabled" if args.run_workflow else "workflow execution disabled"
    resolve_msg = "; SDP ticket resolution enabled" if args.resolve_sdp_ticket else ""
    log(f"Polling SDP every {args.interval}s for {template_msg!r}; {mode_msg}{resolve_msg}.")

    if args.once:
        stats = await engine.poll_once(
            engine_started_at_ms=engine_started_at_ms,
            options=options,
        )
        log(f"POLL_DONE stats={stats}")
        return

    await engine.poll_forever(
        engine_started_at_ms=engine_started_at_ms,
        interval_seconds=args.interval,
        options=options,
    )


if __name__ == "__main__":
    asyncio.run(main_async())
