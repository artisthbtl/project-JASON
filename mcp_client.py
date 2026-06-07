from langchain_mcp_adapters.client import MultiServerMCPClient


async def get_mcp_tools():
    client = MultiServerMCPClient(
        {
            "AWS MCP Server": {
                "command": "uvx",
                "args": [
                    "mcp-proxy-for-aws@latest",
                    "https://aws-mcp.us-east-1.api.aws/mcp",
                ],
                "transport": "stdio",
            }
        }
    )

    tools = await client.get_tools()

    return tools