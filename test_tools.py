import asyncio
from mcp_client import get_mcp_tools


async def main():
    tools = await get_mcp_tools()

    print("\nAvailable tools:\n")

    for tool in tools:
        print(tool.name)


asyncio.run(main())