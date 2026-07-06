from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db import (  # noqa: E402
    DB_PATH,
    delete_service_template,
    ensure_engine_started_at_ms,
    get_engine_info,
    get_ticket_payload,
    init_db,
    list_service_templates,
    list_technician_groups,
    list_ticket_jobs,
    reset_db,
    reset_engine_started_at_ms,
    set_service_template_enabled,
    upsert_service_template,
    upsert_technician_group,
)


def dumps(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def resolve_policy_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def load_policy(args: argparse.Namespace) -> dict[str, Any]:
    if args.policy_json:
        return json.loads(args.policy_json)
    if args.policy_file:
        return json.loads(resolve_policy_path(args.policy_file).read_text(encoding="utf-8"))
    raise SystemExit("Either --policy-file or --policy-json is required.")


def cmd_init(_: argparse.Namespace) -> None:
    init_db()
    print(f"Initialized SQLite DB: {DB_PATH}")
    print(dumps({"engine_info": get_engine_info()}))


def cmd_reset(args: argparse.Namespace) -> None:
    if not args.yes:
        raise SystemExit("Refusing to reset DB without --yes.")
    reset_db()
    print(f"Deleted and recreated empty SQLite DB: {DB_PATH}")


def cmd_watermark(args: argparse.Namespace) -> None:
    if args.reset:
        value = reset_engine_started_at_ms()
        print(dumps({"engine_started_at_ms": value, "reset": True, "engine_info": get_engine_info()}))
    else:
        value = ensure_engine_started_at_ms()
        print(dumps({"engine_started_at_ms": value, "reset": False, "engine_info": get_engine_info()}))


def cmd_groups(_: argparse.Namespace) -> None:
    print(dumps(list_technician_groups()))


def cmd_add_group(args: argparse.Namespace) -> None:
    group_id = upsert_technician_group(name=args.name, description=args.description)
    print(dumps({"group_id": group_id, "name": args.name}))


def cmd_templates(_: argparse.Namespace) -> None:
    print(dumps(list_service_templates()))


def cmd_add_template(args: argparse.Namespace) -> None:
    policy = load_policy(args)
    group_id = upsert_technician_group(
        name=args.group_name,
        description=args.group_description,
    )
    template_id = upsert_service_template(
        sdp_template_id=args.sdp_template_id,
        template_name=args.template_name,
        owning_group_id=group_id,
        policy=policy,
        is_enabled=not args.disabled,
    )
    print(dumps({"group_id": group_id, "service_template_id": template_id}))


def cmd_set_template(args: argparse.Namespace) -> None:
    affected = set_service_template_enabled(args.identifier, args.enabled)
    print(dumps({"affected_rows": affected, "enabled": args.enabled}))


def cmd_delete_template(args: argparse.Namespace) -> None:
    if not args.yes:
        raise SystemExit("Refusing to delete template without --yes.")
    affected = delete_service_template(args.identifier)
    print(dumps({"affected_rows": affected, "deleted": True}))


def cmd_jobs(_: argparse.Namespace) -> None:
    print(dumps(list_ticket_jobs()))


def cmd_payload(args: argparse.Namespace) -> None:
    print(dumps(get_ticket_payload(args.ticket_id)))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage the local automation SQLite database.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="Create schema if missing.")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("reset", help="Delete and recreate the DB schema.")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_reset)

    p = sub.add_parser("watermark", help="Show or reset engine startup watermark.")
    p.add_argument("--reset", action="store_true")
    p.set_defaults(func=cmd_watermark)

    p = sub.add_parser("groups", help="List technician groups.")
    p.set_defaults(func=cmd_groups)

    p = sub.add_parser("add-group", help="Create or update a technician group.")
    p.add_argument("--name", required=True)
    p.add_argument("--description", default=None)
    p.set_defaults(func=cmd_add_group)

    p = sub.add_parser("templates", help="List service templates.")
    p.set_defaults(func=cmd_templates)

    p = sub.add_parser("add-template", help="Create or update a supported SDP service template.")
    p.add_argument("--group-name", required=True)
    p.add_argument("--group-description", default=None)
    p.add_argument("--sdp-template-id", required=True)
    p.add_argument("--template-name", required=True)
    p.add_argument("--policy-file", default=None)
    p.add_argument("--policy-json", default=None)
    p.add_argument("--disabled", action="store_true")
    p.set_defaults(func=cmd_add_template)

    p = sub.add_parser("enable-template", help="Enable a service template by id, SDP id, or name.")
    p.add_argument("identifier")
    p.set_defaults(func=cmd_set_template, enabled=True)

    p = sub.add_parser("disable-template", help="Disable a service template by id, SDP id, or name.")
    p.add_argument("identifier")
    p.set_defaults(func=cmd_set_template, enabled=False)

    p = sub.add_parser("delete-template", help="Delete a service template by id, SDP id, or name.")
    p.add_argument("identifier")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_delete_template)

    p = sub.add_parser("jobs", help="List ticket jobs.")
    p.set_defaults(func=cmd_jobs)

    p = sub.add_parser("payload", help="Show stored raw/normalized payload for a ticket.")
    p.add_argument("ticket_id")
    p.set_defaults(func=cmd_payload)

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
