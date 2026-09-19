"""Tiny local client for testing the binnacle MCP server.

Usage:
    .venv/bin/python scripts/mcp_client.py                          # list tools + resources
    .venv/bin/python scripts/mcp_client.py ping                     # call a tool
    .venv/bin/python scripts/mcp_client.py echo '{"message": "hi"}'
    .venv/bin/python scripts/mcp_client.py binnacle://station       # read a resource
"""

import asyncio
import json
import sys
from pathlib import Path

from fastmcp import Client

TOKEN_FILE = Path.home() / ".config" / "binnacle" / "token"


def _load_token() -> str:
    return (
        TOKEN_FILE.read_text(encoding="utf-8").strip().removeprefix("Bearer ").strip()
    )


async def main() -> None:
    async with Client("http://127.0.0.1:8000/mcp", auth=_load_token()) as client:
        if len(sys.argv) < 2:
            for tool in await client.list_tools():
                # MCP SDK v2 renamed inputSchema to input_schema.
                schema = getattr(tool, "input_schema", None) or tool.inputSchema
                params = ", ".join(schema.get("properties", {}))
                print(f"{tool.name}({params}): {tool.description}")
            for res in await client.list_resources():
                print(f"{res.uri}: {res.name}")
            for tpl in await client.list_resource_templates():
                print(f"{tpl.uriTemplate}: {tpl.name}")
            return
        name = sys.argv[1]
        if "://" in name:  # a resource URI rather than a tool name
            for block in await client.read_resource(name):
                print(getattr(block, "text", block))
            return
        arguments = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        result = await client.call_tool(name, arguments)
        print(result.data)


asyncio.run(main())
