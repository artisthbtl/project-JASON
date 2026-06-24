from typing import Any, List, TypedDict


class AgentState(TypedDict, total=False):
    """State shared by the simple LangGraph PoC workflow."""

    # Initial input from scripts/test_agent.py for now.
    ticket_input: dict[str, Any]

    # Optional message history/debug fields.
    messages: List[Any]

    # planning_read_only output.
    execution_plan: str

    # approval_gate output.
    approval_decision: str
    approval_reason: str

    # execution_agent output.
    execution_result: str

    # Final workflow bookkeeping.
    workflow_status: str
    final_output: str
