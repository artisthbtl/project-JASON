import asyncio

from agent import build_agent


async def main():

    agent = await build_agent()

    response = await agent.ainvoke(
        "Use AWS MCP and perform aws sts get-caller-identity"
    )

    print(response)


asyncio.run(main())