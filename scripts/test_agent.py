import asyncio
from langchain_core.messages import HumanMessage

from src.agent import build_agent


async def main():
    agent = await build_agent()

    response = await agent.ainvoke(
        {
            "messages": [
                HumanMessage(
                    content="Use AWS MCP and perform aws sts get-caller-identity"
                )
            ]
        }
    )

    print("Full response:", response)
    print("\nFinal output:", response["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(main())