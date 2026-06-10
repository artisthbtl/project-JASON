# agent.py
from langchain.agents import create_agent
from llm import llm
from mcp_client import get_mcp_tools

async def build_agent():
    tools = await get_mcp_tools()
    
    # create_agent is the new standard replacement for create_react_agent
    return create_agent(llm, tools)