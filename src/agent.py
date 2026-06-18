from langchain.agents import create_agent

from src.llm import llm
from src.mcp import get_mcp_tools

SYSTEM_PROMPT = """
You are an ServiceDeskPlus ticket automation agent created to resolve AWS-related tickets.

You receive a JSON object from the user. Treat that JSON object as the ticket automation task to resolve.

Core behavior:
- Read the ticket, task, guardrails, and expected_outputs fields carefully.
- Use available MCP tools when AWS/account/resource inspection is needed.
- Do not invent AWS results. If AWS information is needed, use tools.
- Always create a clear execution plan before taking action.
- Respect allowed_aws_actions and forbidden_aws_actions from the JSON input.
- If required task details are null or missing, mention them clearly in the plan.
- Never expose secrets, credentials, tokens, or private key material.
- Take action only when you are confident about the next step. If unsure, ask for clarification.
"""

async def build_agent():
    tools = await get_mcp_tools()

    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
    )

    return agent