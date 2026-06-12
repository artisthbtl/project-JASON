# jason/agent.py

import asyncio
from langchain.agents import create_agent

from src.llm import llm
from src.mcp import get_mcp_tools


SYSTEM_PROMPT = """
You are JASON, an AWS cloud and ticket automation agent.

Rules:
- Use available MCP tools when the user asks you to inspect AWS/account/tool data.
- Do not invent AWS results.
- If a tool fails, explain the failure and suggest the next action.
- For ticket automation, produce clear, structured, concise output.
- Never expose secrets, credentials, tokens, or private key material.
"""


def _load_tools_sync():
    return asyncio.run(get_mcp_tools())


tools = _load_tools_sync()

agent = create_agent(
    model=llm,
    tools=tools,
    system_prompt=SYSTEM_PROMPT,
)


async def build_agent():
    return agent