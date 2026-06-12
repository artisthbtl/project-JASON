# test_agent.py
import asyncio
from agent import build_agent
from langchain_core.messages import SystemMessage, HumanMessage

async def main():
    agent = await build_agent()
    
    response = await agent.ainvoke({
        "messages": [
            SystemMessage(content="You are an AWS cloud agent. You MUST use the provided tools to fetch information. Do NOT answer from your general knowledge."),
            HumanMessage(content="Use AWS MCP and perform aws sts get-caller-identity")
        ]
    })
    
    # Print full response to see model's intermediate reasoning
    print("Full response:", response)
    print("\nFinal output:", response["messages"][-1].content)

if __name__ == "__main__":
    asyncio.run(main())