# scripts/inspect_tools.py

import asyncio
import json

from src.mcp import get_mcp_tools


async def main():
    tools = await get_mcp_tools()

    for tool in tools:
        print("\n" + "=" * 80)
        print("NAME:", tool.name)
        print("DESCRIPTION:", tool.description)

        try:
            print("ARGS SCHEMA:")
            print(json.dumps(tool.args_schema.model_json_schema(), indent=2))
        except Exception as e:
            print("Could not print args_schema:", e)


if __name__ == "__main__":
    asyncio.run(main())