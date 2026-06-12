from langchain.agents import create_agent
from llm import llm
from mcp_client import get_mcp_tools
from langchain_core.tools import Tool

async def build_agent():
    tools = await get_mcp_tools()
    
    llm_with_tools = llm.bind_tools(tools)
    
    return create_agent(llm_with_tools, tools)