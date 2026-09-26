"""run_command's MCP surface, pinned.

The run_command shadow-prediction experiment (removed 2026-09-27) only
logged; removing it must not change what a client sees. The hash covers the
name, description, input schema, output schema and annotations as the
in-memory client lists them, measured on master b040984 before the removal.
When run_command's surface changes on purpose, update the hash in the same
change and say why in the commit.
"""

import asyncio
import hashlib
import json

from fastmcp import Client

from binnacle import server

RUN_COMMAND_SURFACE_SHA256 = (
    "7095ec3b1389a6e263819e9c2b108f4a8e39ff887a1755b2987e5e9efeae5584"
)


def _surface() -> dict:
    async def go():
        async with Client(server.mcp) as c:
            return await c.list_tools()

    tool = next(t for t in asyncio.run(go()) if t.name == "run_command")
    return {
        "name": tool.name,
        "description": tool.description,
        "input": tool.input_schema,
        "output": tool.output_schema,
        "annotations": (
            tool.annotations.model_dump(exclude_none=True) if tool.annotations else None
        ),
    }


def test_run_command_surface_is_pinned():
    digest = hashlib.sha256(json.dumps(_surface(), sort_keys=True).encode()).hexdigest()
    assert digest == RUN_COMMAND_SURFACE_SHA256
