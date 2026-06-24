import json
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from src.agent import build_executor_agent, build_planner_agent
from src.mcp import get_mcp_tools
from src.state import AgentState


# TO-DO: validate_ticket
# Static deterministic validation will later check ticket_id, requester, technician,
# AWS account, task_type, resource names, supported template, and AWS-only scope.

# TO-DO: retrieve_company_policy
# RAG retrieval will later fetch company policy, WAF baseline rules, approval rules,
# region/account constraints, and ServiceDeskPlus resolution templates.

# TO-DO: resolution_draft
# Template-based ServiceDeskPlus resolution drafting will later use verified results
# and company-required ticket closure format.


def _ticket_id(ticket_input: dict[str, Any]) -> str:
    return str(ticket_input.get("ticket", {}).get("ticket_id", "unknown-ticket"))


def _agent_config(config: RunnableConfig | None, ticket_input: dict[str, Any], phase: str) -> RunnableConfig:
    """Create a separate checkpoint thread for planner and executor agents."""
    configurable = dict((config or {}).get("configurable", {}))
    base_thread_id = configurable.get("thread_id", f"ticket-{_ticket_id(ticket_input)}")
    configurable["thread_id"] = f"{base_thread_id}:{phase}"
    return {"configurable": configurable}


def _latest_content(response: dict[str, Any]) -> str:
    messages = response.get("messages", [])
    if not messages:
        return ""
    return str(messages[-1].content)


async def build_workflow():
    # Start the MCP client once, then share the same tool definitions between both agents.
    tools = await get_mcp_tools()
    planner_agent = await build_planner_agent(tools=tools)
    executor_agent = await build_executor_agent(tools=tools)

    async def planning_read_only(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
        ticket_input = state["ticket_input"]

        message = HumanMessage(
            content=(
                "Create a read-only execution plan for this ServiceDeskPlus AWS ticket. "
                "Do not execute or modify AWS resources.\n\n"
                f"Input JSON:\n{json.dumps(ticket_input, indent=2)}"
            )
        )

        response = await planner_agent.ainvoke(
            {"messages": [message]},
            config=_agent_config(config, ticket_input, "planner"),
        )

        execution_plan = _latest_content(response)

        return {
            "execution_plan": execution_plan,
            "workflow_status": "planned",
        }

    def approval_gate(state: AgentState) -> AgentState:
        ticket_input = state["ticket_input"]
        ticket = ticket_input.get("ticket", {})
        task = ticket_input.get("task", {})
        resources = task.get("resources", [])
        waf_names = [resource.get("waf_name") for resource in resources if resource.get("waf_name")]
        technician = ticket.get("technician", {})
        requester = ticket.get("requester", {})

        print("\n" + "=" * 90)
        print("APPROVAL REQUIRED")
        print("=" * 90)
        print(f"Ticket ID      : {ticket.get('ticket_id')}")
        print(f"Subject        : {ticket.get('subject')}")
        print(f"Requester      : {requester.get('name')} <{requester.get('email')}>")
        print(f"Technician     : {technician.get('name')} <{technician.get('email')}>")
        print(f"Task Type      : {task.get('task_type')}")
        print(f"AWS Account    : {resources[0].get('account_alias') if resources else None}")
        print(f"AWS Account ID : {resources[0].get('account_id') if resources else None}")
        print(f"Region         : {resources[0].get('region') if resources else None}")
        print(f"WAF Names      : {', '.join(waf_names) if waf_names else 'N/A'}")
        print("\nExecution plan from planning_read_only:")
        print("-" * 90)
        print(state.get("execution_plan", ""))
        print("-" * 90)

        while True:
            decision = input("Type 'approve' to execute or 'reject' to stop: ").strip().lower()
            if decision in {"approve", "approved"}:
                return {
                    "approval_decision": "approved",
                    "approval_reason": "Technician approved execution from terminal input.",
                    "workflow_status": "approved",
                }
            if decision in {"reject", "rejected"}:
                return {
                    "approval_decision": "rejected",
                    "approval_reason": "Technician rejected execution from terminal input.",
                    "workflow_status": "rejected",
                    "final_output": "Workflow stopped. Technician rejected the execution plan.",
                }
            print("Invalid input. Please type exactly 'approve' or 'reject'.")

    async def execution_agent(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
        ticket_input = state["ticket_input"]

        if state.get("approval_decision") != "approved":
            return {
                "workflow_status": "blocked",
                "execution_result": "Execution blocked because approval_decision is not approved.",
                "final_output": "Workflow blocked before execution.",
            }

        message = HumanMessage(
            content=(
                "Execute this approved ServiceDeskPlus AWS ticket automation task. "
                "Follow only the approved plan. Do not re-plan from scratch.\n\n"
                f"Approval decision: {state.get('approval_decision')}\n"
                f"Approval reason: {state.get('approval_reason')}\n\n"
                f"Approved execution plan:\n{state.get('execution_plan')}\n\n"
                f"Original ticket JSON:\n{json.dumps(ticket_input, indent=2)}"
            )
        )

        response = await executor_agent.ainvoke(
            {"messages": [message]},
            config=_agent_config(config, ticket_input, "executor"),
        )

        execution_result = _latest_content(response)

        return {
            "execution_result": execution_result,
            "workflow_status": "completed",
            "final_output": execution_result,
        }

    def route_after_approval(state: AgentState) -> str:
        if state.get("approval_decision") == "approved":
            return "approved"
        return "rejected"

    graph = StateGraph(AgentState)

    graph.add_node("planning_read_only", planning_read_only)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("execution_agent", execution_agent)

    graph.add_edge(START, "planning_read_only")
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
