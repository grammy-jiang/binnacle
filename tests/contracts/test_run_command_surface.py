"""run_command's MCP surface, pinned.

The run_command shadow-prediction experiment (removed 2026-09-27) only
logged; removing it must not change what a client sees. The hash covers the
name, description, output schema, annotations and a normalized input schema,
measured on master b040984 before the removal.

The input schema is normalized because its JSON form depends on the Python
version: an optional parameter is `anyOf [T, null]` on 3.11+ and a nested
`anyOf` with the description inside on 3.10. The normalized form keeps what
a client relies on: per parameter the non-null types, the constraints, the
default and the description, plus the required list.

When run_command's surface changes on purpose, update the hash in the same
change and say why in the commit.
"""

import asyncio
import hashlib
import json
from collections.abc import Iterator

from fastmcp import Client

from binnacle import server

RUN_COMMAND_SURFACE_SHA256 = (
    "52a4bd22d2b03f42b4c7b50675e98956cbe6ca0638a6bddb5f409ac9d90c61f7"
)
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


def _nodes(schema: dict) -> Iterator[dict]:
    yield schema
    for branch in schema.get("anyOf", ()):
        yield from _nodes(branch)


def _parameter(schema: dict) -> dict:
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


def _surface() -> dict:
    async def go():
        async with Client(server.mcp) as c:
            return await c.list_tools()

    tool = next(t for t in asyncio.run(go()) if t.name == "run_command")
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
                name: _parameter(spec) for name, spec in schema["properties"].items()
            },
            "required": sorted(schema.get("required", [])),
        },
    }


def test_run_command_surface_is_pinned():
    digest = hashlib.sha256(json.dumps(_surface(), sort_keys=True).encode()).hexdigest()
    assert digest == RUN_COMMAND_SURFACE_SHA256


def test_normalization_reads_both_optional_forms():
    new_form = {
        "anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}],
        "default": None,
        "description": "N lines.",
    }
    old_form = {
        "anyOf": [
            {
                "anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}],
                "description": "N lines.",
            },
            {"type": "null"},
        ],
        "default": None,
    }
    assert _parameter(new_form) == _parameter(old_form)
    assert _parameter({"type": ["string", "null"]})["types"] == ["string"]
