import copy
import json
import re
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCUMENT_DIR = PROJECT_ROOT / "knowledge_base"
INDEX_PATH = DOCUMENT_DIR / "index.json"


def _normalize_key(value: str) -> str:
    """Normalize human-readable schema/template names into file-safe lookup keys."""
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Document not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _normalized_payload(ticket_input: dict[str, Any]) -> dict[str, Any]:
    """Return the generic SDP normalized payload when the engine envelope is used."""
    normalized_input = ticket_input.get("normalized_input")
    if isinstance(normalized_input, dict):
        return normalized_input
    return ticket_input


def _embedded_policy(ticket_input: dict[str, Any]) -> dict[str, Any]:
    policy = ticket_input.get("policy")
    return policy if isinstance(policy, dict) else {}


def _raw_task(ticket_input: dict[str, Any]) -> dict[str, Any]:
    task = ticket_input.get("task")
    return task if isinstance(task, dict) else {}


def _raw_resources(ticket_input: dict[str, Any]) -> list[dict[str, Any]]:
    """Return workflow resources without changing the public engine input shape."""
    normalized_input = ticket_input.get("normalized_input")
    if isinstance(normalized_input, dict):
        description = normalized_input.get("description")
        rows = description.get("rows") if isinstance(description, dict) else []
        return [copy.deepcopy(row) for row in rows if isinstance(row, dict)]

    task = _raw_task(ticket_input)
    resources = task.get("resources") or []
    return [copy.deepcopy(resource) for resource in resources if isinstance(resource, dict)]


def _candidate_schema_names(ticket_input: dict[str, Any]) -> list[str]:
    """
    Return schema identifiers in priority order.

    Supports both the old manual test shape and the current engine envelope:
    {"normalized_input": {"ticket": ..., "description": ...}, "policy": ...}.
    """
    normalized = _normalized_payload(ticket_input)
    ticket = normalized.get("ticket", {}) or {}
    task = _raw_task(ticket_input)
    policy = _embedded_policy(ticket_input)

    candidates = [
        ticket_input.get("name"),
        ticket.get("request_schema"),
        ticket.get("template"),
        task.get("task_type"),
        policy.get("schema_name"),
        policy.get("task_type"),
    ]

    return [str(item).strip() for item in candidates if item]


def resolve_task_document_key(ticket_input: dict[str, Any]) -> str:
    """Resolve the matching company policy document key for a ticket."""
    index = _load_json(INDEX_PATH)
    aliases = index.get("aliases", {})
    normalized_aliases = {_normalize_key(k): v for k, v in aliases.items()}

    for name in _candidate_schema_names(ticket_input):
        if name in aliases:
            return aliases[name]

        normalized = _normalize_key(name)
        if normalized in normalized_aliases:
            return normalized_aliases[normalized]

        direct_path = DOCUMENT_DIR / f"{normalized}.json"
        if direct_path.exists():
            return normalized

    raise ValueError(
        "No company policy document matched this ticket. "
        f"Tried candidates: {_candidate_schema_names(ticket_input)}"
    )


def load_task_document(ticket_input: dict[str, Any]) -> dict[str, Any]:
    """Load the task-specific company policy document."""
    document_key = resolve_task_document_key(ticket_input)
    document = _load_json(DOCUMENT_DIR / f"{document_key}.json")
    document["_document_key"] = document_key
    return document


def _compact_person(person: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": person.get("name"),
        "email": person.get("email") or person.get("email_id"),
    }


def _compact_ticket(ticket_input: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalized_payload(ticket_input)
    ticket = normalized.get("ticket", {}) or {}
    requester = ticket.get("requester", {}) or {}
    technician = ticket.get("technician", {}) or {}

    return {
        "ticket_id": ticket.get("ticket_id") or ticket.get("id"),
        "subject": ticket.get("subject"),
        "status": ticket.get("status"),
        "template": ticket.get("template"),
        "service_category": ticket.get("service_category"),
        "priority": ticket.get("priority"),
        "requester": _compact_person(requester),
        "technician": _compact_person(technician),
    }


def _legacy_rules_to_resource_fields(resource: dict[str, Any]) -> dict[str, Any]:
    """Support older PoC inputs that still place WAF rule groups under rules."""
    copied = copy.deepcopy(resource)
    rules = copied.pop("rules", None)

    if isinstance(rules, dict):
        if "default_action" in rules and "default_action" not in copied:
            copied["default_action"] = rules["default_action"]
        if "managed_rule_groups" in rules and "managed_rule_groups" not in copied:
            copied["managed_rule_groups"] = rules["managed_rule_groups"]

    return copied


def _merge_resource_defaults(
    resource: dict[str, Any],
    document: dict[str, Any],
) -> dict[str, Any]:
    """Merge ticket-specific resource data with task document defaults."""
    merged = _legacy_rules_to_resource_fields(resource)

    for key, value in (document.get("defaults", {}) or {}).items():
        merged.setdefault(key, copy.deepcopy(value))

    for key, value in (document.get("resource_defaults", {}) or {}).items():
        merged.setdefault(key, copy.deepcopy(value))

    return merged


def _missing_fields(resources: list[dict[str, Any]], required_fields: list[str]) -> list[dict[str, Any]]:
    missing = []
    for index, resource in enumerate(resources):
        fields = [field for field in required_fields if not resource.get(field)]
        if fields:
            missing.append({"resource_index": index, "missing_fields": fields})
    return missing


def build_planner_context(
    ticket_input: dict[str, Any],
    task_document: dict[str, Any],
) -> dict[str, Any]:
    """
    Build the compact object passed to the planning agent.

    This is intentionally not a full enriched ticket. It contains only the data
    the planner needs to create an execution plan. Workflow-control values such
    as approval status, document key, and graph routing stay in LangGraph state.
    """
    raw_task = _raw_task(ticket_input)
    raw_resources = _raw_resources(ticket_input)
    resources = [_merge_resource_defaults(resource, task_document) for resource in raw_resources]
    required_resource_fields = task_document.get("required_resource_fields", []) or []

    return {
        "ticket": _compact_ticket(ticket_input),
        "task": {
            "task_type": task_document.get("task_type") or raw_task.get("task_type"),
            "service": task_document.get("service") or raw_task.get("service"),
            "operation": task_document.get("operation") or raw_task.get("operation"),
            "description": task_document.get("description") or raw_task.get("description"),
            "required_resource_fields": required_resource_fields,
            "resources": resources,
        },
        "instructions": {
            "planning_rules": copy.deepcopy(task_document.get("planning_rules", {})),
            "execution_rules": copy.deepcopy(task_document.get("execution_rules", {})),
        },
        "resolution": copy.deepcopy(task_document.get("resolution", {})),
        "validation": {
            "missing_required_fields": _missing_fields(resources, required_resource_fields),
        },
    }


# Backward-compatible aliases for older scripts/imports.
def load_static_policy_document(ticket_input: dict[str, Any]) -> dict[str, Any]:
    return load_task_document(ticket_input)


def enrich_ticket_with_policy(
    ticket_input: dict[str, Any],
    policy_document: dict[str, Any],
) -> dict[str, Any]:
    return build_planner_context(ticket_input, policy_document)
