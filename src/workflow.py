import json
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from src.agent import build_executor_agent, build_planner_agent
from src.json_utils import extract_json_object
from src.knowledge import build_planner_context, load_task_document
from src.mcp import get_mcp_tools
from src.state import AgentState


def _ticket_id(ticket_input: dict[str, Any]) -> str:
    return str(ticket_input.get("ticket", {}).get("ticket_id", "unknown-ticket"))


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


async def build_workflow():
    # Start the MCP client once, then share the same tool definitions between both agents.
    tools = await get_mcp_tools()
    planner_agent = await build_planner_agent(tools=tools)
    executor_agent = await build_executor_agent(tools=tools)

    def load_task_context(state: AgentState) -> AgentState:
        """
        Load the task-specific company policy document and build planner_context.

        The planner sees only planner_context. Internal routing details such as
        document key/path stay in graph state and are not passed to the model.
        """
        ticket_input = state["ticket_input"]
        task_document = load_task_document(ticket_input)
        planner_context = build_planner_context(ticket_input, task_document)

        return {
            "task_document_key": task_document.get("_document_key"),
            "task_document": task_document,
            "planner_context": planner_context,
            "workflow_status": "context_loaded",
        }

    async def planning_read_only(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
        ticket_input = state["ticket_input"]
        planner_context = state["planner_context"]

        message = HumanMessage(
            content=(
                "Create a read-only execution plan from this planner_context. "
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

        return {
            "execution_plan": execution_plan,
            "workflow_status": "planned",
        }

    def approval_gate(state: AgentState) -> AgentState:
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
        print("\nApproved execution plan candidate:")
        print("-" * 90)
        print(_json_dump(execution_plan))
        print("-" * 90)

        while True:
            decision = input("Type 'approve' to execute or 'reject' to stop: ").strip().lower()
            if decision in {"approve", "approved"}:
                return {
                    "approval_decision": "approved",
                    "approval_reason": "Terminal approval.",
                    "workflow_status": "approved",
                }
            if decision in {"reject", "rejected"}:
                return {
                    "approval_decision": "rejected",
                    "approval_reason": "Terminal rejection.",
                    "workflow_status": "rejected",
                    "final_output": "Workflow stopped. Execution plan was rejected.",
                }
            print("Invalid input. Please type exactly 'approve' or 'reject'.")

    async def execution_agent(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
        ticket_input = state["ticket_input"]

        if state.get("approval_decision") != "approved":
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

        return {
            "execution_result": execution_result,
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
