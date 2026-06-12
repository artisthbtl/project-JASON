import asyncio
from src.mcp import get_mcp_tools


async def main():
    tools = await get_mcp_tools()

    print("\nAvailable tools:\n")

    for tool in tools:
        print(tool.name)


asyncio.run(main())