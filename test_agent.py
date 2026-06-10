# test_agent.py
import asyncio
from agent import build_agent
from langchain_core.messages import SystemMessage, HumanMessage

async def main():
    agent = await build_agent()

    # Pass the messages structure to the agent
    response = await agent.ainvoke({
        "messages": [
            SystemMessage(content="You are an AWS cloud agent. You MUST use the provided tools to fetch information. Do NOT answer from your general knowledge."),
            HumanMessage(content="Use AWS MCP and perform aws sts get-caller-identity")
        ]
    })
    
    # The final message will contain the result of the tool execution
    print(response["messages"][-1].content)

if __name__ == "__main__":
    asyncio.run(main())