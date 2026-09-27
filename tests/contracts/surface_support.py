"""What a client is served, read through the real server.

A *profile* is the surface one kind of client sees. The server builds it in
``ClientToolVisibility`` (src/binnacle/visibility.py): the client name comes
from the session (the initialize handshake on a legacy session, ``_meta`` on
modern discovery) and ``Settings.client_tools`` maps a name prefix to the
tools that client is served; a name that matches no prefix gets every tool.
``served`` connects fastmcp's in-memory Client with that client name, so each
profile goes through the same middleware as a real connection.

``surface`` normalizes one tool for hashing. The input schema's JSON form
depends on the Python version: an optional parameter is ``anyOf [T, null]``
on 3.11+ and a nested ``anyOf`` with the description inside on 3.10. The
normalized form keeps what a client relies on: per parameter the non-null
types, the constraints, the default and the description, plus the required
list. The output schemas are static dicts in the tool modules and are kept
as served.
"""

import asyncio
import hashlib
import json
from collections.abc import Iterator

import mcp.types
from fastmcp import Client

from binnacle import server

#: The client name each pinned profile connects with. ChatGPT names itself
#: 'openai-mcp' on a legacy session and 'openai-mcp(ChatGPT)' on modern
#: discovery; None is a client whose name matches no client_tools prefix.
PROFILES: dict[str, str | None] = {"chatgpt": "openai-mcp", "default": None}

CONSTRAINTS = (
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "pattern",
    "enum",
    "items",
)


def served(
    client_name: str | None = None, mode: str | None = None
) -> tuple[list[mcp.types.Tool], str | None]:
    """The tools and the server instructions a client of this name receives."""

    async def go() -> tuple[list[mcp.types.Tool], str | None]:
        kwargs: dict = {}
        if client_name is not None:
            kwargs["client_info"] = mcp.types.Implementation(
                name=client_name, version="1"
            )
        if mode is not None:
            kwargs["mode"] = mode
        async with Client(server.mcp, **kwargs) as client:
            return await client.list_tools(), client.instructions

    return asyncio.run(go())


def _nodes(schema: dict) -> Iterator[dict]:
    yield schema
    for branch in schema.get("anyOf", ()):
        yield from _nodes(branch)


def parameter(schema: dict) -> dict:
    """One input parameter in a form that is the same on every Python."""
    types: set[str] = set()
    constraints: dict = {}
    description = None
    for node in _nodes(schema):
        declared = node.get("type")
        names = [declared] if isinstance(declared, str) else (declared or [])
        types.update(name for name in names if name != "null")
        constraints.update({key: node[key] for key in CONSTRAINTS if key in node})
        description = description or node.get("description")
    return {
        "types": sorted(types),
        "constraints": constraints,
        "default": schema.get("default"),
        "description": description,
    }


def surface(tool: mcp.types.Tool) -> dict:
    """Name, description, output schema, annotations, normalized input."""
    schema = tool.input_schema
    return {
        "name": tool.name,
        "description": tool.description,
        "output": tool.output_schema,
        "annotations": (
            tool.annotations.model_dump(exclude_none=True) if tool.annotations else None
        ),
        "input": {
            "properties": {
                name: parameter(spec) for name, spec in schema["properties"].items()
            },
            "required": sorted(schema.get("required", [])),
        },
    }


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
