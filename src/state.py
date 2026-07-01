from typing import Any, List, TypedDict


class AgentState(TypedDict, total=False):
    """State shared by the LangGraph PoC workflow."""

    # Initial normalized ticket input from ServiceDeskPlus / test script.
    ticket_input: dict[str, Any]

    # Internal task document lookup data. These are not passed directly to agents.
    task_document_key: str
    task_document: dict[str, Any]

    # Compact model-facing context for the planning node only.
    planner_context: dict[str, Any]

    # Optional message history/debug fields.
    messages: List[Any]

    # planning_read_only output. This is the only task source for the executor.
    execution_plan: dict[str, Any]

    # approval_gate output.
    approval_decision: str
    approval_reason: str

    # execution_agent output.
    execution_result: dict[str, Any]

    # Final workflow bookkeeping.
    workflow_status: str
    final_output: str
