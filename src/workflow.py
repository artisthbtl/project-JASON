import json
import time
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from src.agent import build_executor_agent, build_planner_agent
from src.json_utils import extract_json_object
from src.knowledge import build_planner_context, load_task_document
from src.mcp import get_mcp_tools
from src.state import AgentState


def _timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _node_log(state: AgentState, message: str) -> None:
    if bool(state.get("verbose", True)):
        print(f"[{_timestamp()}] {message}", flush=True)


def _normalized_payload(ticket_input: dict[str, Any]) -> dict[str, Any]:
    normalized_input = ticket_input.get("normalized_input")
    return normalized_input if isinstance(normalized_input, dict) else ticket_input


def _ticket_id(ticket_input: dict[str, Any]) -> str:
    normalized = _normalized_payload(ticket_input)
    ticket = normalized.get("ticket") if isinstance(normalized.get("ticket"), dict) else {}
    return str(ticket.get("ticket_id") or ticket.get("id") or "unknown-ticket")


def _agent_config(config: RunnableConfig | None, ticket_input: dict[str, Any], phase: str) -> RunnableConfig:
    """Create separate checkpoint threads for planner and executor agents."""
    configurable = dict((config or {}).get("configurable", {}))
    base_thread_id = configurable.get("thread_id", f"ticket-{_ticket_id(ticket_input)}")
    configurable["thread_id"] = f"{base_thread_id}:{phase}"
    return {"configurable": configurable}


def _latest_content(response: dict[str, Any]) -> str:
    messages = response.get("messages", [])
    if not messages:
        return ""
    return str(messages[-1].content)


def _json_dump(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _usage_from_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {"input_token_count": 0, "output_token_count": 0, "total_token_count": 0}

    input_count = (
        value.get("input_token_count")
        or value.get("input_tokens")
        or value.get("prompt_tokens")
        or value.get("prompt_token_count")
        or 0
    )
    output_count = (
        value.get("output_token_count")
        or value.get("output_tokens")
        or value.get("completion_tokens")
        or value.get("completion_token_count")
        or 0
    )
    total_count = value.get("total_token_count") or value.get("total_tokens") or 0

    input_count = _as_int(input_count)
    output_count = _as_int(output_count)
    total_count = _as_int(total_count) or input_count + output_count

    return {
        "input_token_count": input_count,
        "output_token_count": output_count,
        "total_token_count": total_count,
    }


def _message_usage(message: Any) -> dict[str, int]:
    candidates = [
        getattr(message, "usage_metadata", None),
        getattr(message, "response_metadata", None),
        getattr(message, "additional_kwargs", None),
    ]

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        nested = candidate.get("usage") if isinstance(candidate.get("usage"), dict) else candidate
        extracted = _usage_from_mapping(nested)
        if (
            extracted["input_token_count"]
            or extracted["output_token_count"]
            or extracted["total_token_count"]
        ):
            return extracted

    return {"input_token_count": 0, "output_token_count": 0, "total_token_count": 0}


def _agent_response_usage(response: dict[str, Any]) -> dict[str, int]:
    total = {"input_token_count": 0, "output_token_count": 0, "total_token_count": 0}
    for message in response.get("messages", []) or []:
        usage = _message_usage(message)
        total["input_token_count"] += usage["input_token_count"]
        total["output_token_count"] += usage["output_token_count"]
        total["total_token_count"] += usage["total_token_count"]
    return total


def _merge_token_usage(existing: dict[str, Any] | None, phase: str, phase_usage: dict[str, int]) -> dict[str, Any]:
    result: dict[str, Any] = dict(existing or {})
    result[phase] = phase_usage

    planner = result.get("planner") if isinstance(result.get("planner"), dict) else {}
    executor = result.get("executor") if isinstance(result.get("executor"), dict) else {}
    result["total"] = {
        "input_token_count": _as_int(planner.get("input_token_count")) + _as_int(executor.get("input_token_count")),
        "output_token_count": _as_int(planner.get("output_token_count")) + _as_int(executor.get("output_token_count")),
        "total_token_count": _as_int(planner.get("total_token_count")) + _as_int(executor.get("total_token_count")),
    }
    return result


async def build_workflow():
    # Start the MCP client once, then share the same tool definitions between both agents.
    tools = await get_mcp_tools()
    planner_agent = await build_planner_agent(tools=tools)
    executor_agent = await build_executor_agent(tools=tools)

    def load_task_context(state: AgentState) -> AgentState:
        """
        Load task policy and build planner_context.

        Preferred source is state["task_document"], which lets the centralized
        SDP engine pass the service_template.policy stored in SQLite. The older
        knowledge_base lookup remains as a fallback for manual tests.
        """
        _node_log(state, "WORKFLOW_NODE load_task_context.start")
        ticket_input = state["ticket_input"]
        task_document = state.get("task_document")

        if not isinstance(task_document, dict) or not task_document:
            embedded_policy = ticket_input.get("policy")
            task_document = embedded_policy if isinstance(embedded_policy, dict) else None

        if not isinstance(task_document, dict) or not task_document:
            task_document = load_task_document(ticket_input)
        else:
            task_document = dict(task_document)
            task_document.setdefault(
                "_document_key",
                task_document.get("schema_name")
                or task_document.get("task_type")
                or ticket_input.get("name")
                or "db_policy",
            )

        planner_context = build_planner_context(ticket_input, task_document)
        _node_log(state, "WORKFLOW_NODE load_task_context.done")

        return {
            "task_document_key": task_document.get("_document_key"),
            "task_document": task_document,
            "planner_context": planner_context,
            "workflow_status": "context_loaded",
        }

    async def planning_read_only(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
        _node_log(state, "WORKFLOW_NODE planning_agent.start")
        ticket_input = state["ticket_input"]
        planner_context = state["planner_context"]

        message = HumanMessage(
            content=(
                "Create a compact read-only execution plan from planner_context. "
                "Do not execute or modify resources. Return JSON only.\n\n"
                f"planner_context:\n{_json_dump(planner_context)}"
            )
        )

        response = await planner_agent.ainvoke(
            {"messages": [message]},
            config=_agent_config(config, ticket_input, "planner"),
        )

        raw_plan = _latest_content(response)
        execution_plan = extract_json_object(raw_plan)
        token_usage = _merge_token_usage(state.get("token_usage"), "planner", _agent_response_usage(response))
        _node_log(state, "WORKFLOW_NODE planning_agent.done")

        return {
            "execution_plan": execution_plan,
            "token_usage": token_usage,
            "workflow_status": "planned",
        }

    def approval_gate(state: AgentState) -> AgentState:
        _node_log(state, "WORKFLOW_NODE approval_gate.waiting")
        planner_context = state["planner_context"]
        ticket = planner_context.get("ticket", {})
        requester = ticket.get("requester", {}) or {}
        technician = ticket.get("technician", {}) or {}
        execution_plan = state.get("execution_plan", {})

        print("\n" + "=" * 90)
        print("APPROVAL REQUIRED")
        print("=" * 90)
        print(f"Ticket ID  : {ticket.get('ticket_id')}")
        print(f"Subject    : {ticket.get('subject')}")
        print(f"Requester  : {requester.get('name')} <{requester.get('email')}>")
        print(f"Technician : {technician.get('name')} <{technician.get('email')}>")
        print(f"Task Type  : {execution_plan.get('task_type')}")
        print("\nExecution plan JSON:")
        print("-" * 90)
        print(_json_dump(execution_plan))
        print("-" * 90)

        while True:
            decision = input("Type 'approve' to execute or 'reject' to stop: ").strip().lower()
            if decision in {"approve", "approved"}:
                _node_log(state, "WORKFLOW_NODE approval_gate.approved")
                return {
                    "approval_decision": "approved",
                    "approval_reason": "Terminal approval.",
                    "workflow_status": "approved",
                }
            if decision in {"reject", "rejected"}:
                _node_log(state, "WORKFLOW_NODE approval_gate.rejected")
                return {
                    "approval_decision": "rejected",
                    "approval_reason": "Terminal rejection.",
                    "workflow_status": "rejected",
                    "final_output": "Workflow stopped. Execution plan was rejected.",
                }
            print("Invalid input. Please type exactly 'approve' or 'reject'.")

    async def execution_agent(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
        _node_log(state, "WORKFLOW_NODE execution_agent.start")
        ticket_input = state["ticket_input"]

        if state.get("approval_decision") != "approved":
            _node_log(state, "WORKFLOW_NODE execution_agent.blocked")
            return {
                "workflow_status": "blocked",
                "execution_result": {
                    "status": "blocked",
                    "errors": ["approval_decision is not approved"],
                },
                "final_output": "Workflow blocked before execution.",
            }

        execution_plan = state["execution_plan"]

        message = HumanMessage(
            content=(
                "Execute this approved execution_plan exactly. "
                "Do not re-plan. Do not use the original ticket as an execution source. "
                "Return JSON only.\n\n"
                f"approval_decision: {state.get('approval_decision')}\n"
                f"approval_reason: {state.get('approval_reason')}\n\n"
                f"execution_plan:\n{_json_dump(execution_plan)}"
            )
        )

        response = await executor_agent.ainvoke(
            {"messages": [message]},
            config=_agent_config(config, ticket_input, "executor"),
        )

        raw_result = _latest_content(response)
        execution_result = extract_json_object(raw_result)
        token_usage = _merge_token_usage(state.get("token_usage"), "executor", _agent_response_usage(response))
        _node_log(state, "WORKFLOW_NODE execution_agent.done")

        return {
            "execution_result": execution_result,
            "token_usage": token_usage,
            "workflow_status": execution_result.get("status", "completed"),
            "final_output": _json_dump(execution_result),
        }

    def route_after_approval(state: AgentState) -> str:
        if state.get("approval_decision") == "approved":
            return "approved"
        return "rejected"

    graph = StateGraph(AgentState)

    graph.add_node("load_task_context", load_task_context)
    graph.add_node("planning_read_only", planning_read_only)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("execution_agent", execution_agent)

    graph.add_edge(START, "load_task_context")
    graph.add_edge("load_task_context", "planning_read_only")
    graph.add_edge("planning_read_only", "approval_gate")
    graph.add_conditional_edges(
        "approval_gate",
        route_after_approval,
        {
            "approved": "execution_agent",
            "rejected": END,
        },
    )
    graph.add_edge("execution_agent", END)

    return graph.compile()
