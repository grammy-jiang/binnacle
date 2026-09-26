"""With read_file.multi_mode = "off" the tool surface is byte-identical to
the surface before the multi-file read candidates (2026-09-27).

The snapshot was generated from origin/master 3ee3399 before any
multi-file code existed. It holds what a client is served: the server
instructions, every tool's name, description, input and output schema and
annotations for an unrestricted client, and the tool names ChatGPT is
served. Regenerate only for a deliberate surface change:
BINNACLE_UPDATE_SURFACE_SNAPSHOT=1 pytest tests/contracts/test_tool_surface_off.py
"""

import asyncio
import json
import os
from pathlib import Path

import mcp.types
from fastmcp import Client

from binnacle import server

SNAPSHOT = Path(__file__).parent / "snapshots" / "tool_surface_off.json"
TOOL_FIELDS = ("name", "description", "inputSchema", "outputSchema", "annotations")


def surface() -> dict:
    async def run() -> dict:
        async with Client(server.mcp) as c:
            tools = await c.list_tools()
        async with Client(
            server.mcp,
            client_info=mcp.types.Implementation(
                name="openai-mcp(ChatGPT)", version="1"
            ),
        ) as c:
            chatgpt = sorted(t.name for t in await c.list_tools())
        dumped = []
        for t in sorted(tools, key=lambda t: t.name):
            d = t.model_dump(mode="json", by_alias=True)
            dumped.append({k: d.get(k) for k in TOOL_FIELDS})
        return {
            "instructions": server.mcp.instructions,
            "tools": dumped,
            "chatgpt_tool_names": chatgpt,
        }

    return asyncio.run(run())


def render(data: dict) -> str:
    return json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def test_off_mode_surface_is_byte_identical():
    current = render(surface())
    if os.environ.get("BINNACLE_UPDATE_SURFACE_SNAPSHOT") == "1":
        SNAPSHOT.write_text(current, encoding="utf-8")
    assert current == SNAPSHOT.read_text(encoding="utf-8")
