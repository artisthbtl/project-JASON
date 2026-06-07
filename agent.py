from llm import llm
from mcp_client import get_mcp_tools


async def build_agent():
    tools = await get_mcp_tools()

    return llm.bind_tools(tools)