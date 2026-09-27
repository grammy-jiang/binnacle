"""search_text's MCP surface, pinned.

The '@context' indexed-discovery pilot was removed on 2026-09-28
(docs/indexed-context-pilot.md). Two pieces of text left the surface: a
sentence of the tool description and a clause of the pattern parameter.
Everything else a client sees must stay byte-identical to master 9b7d6d3,
measured before the removal. The first test proves that: it puts the removed
text back into today's surface and compares the hash with the one measured
on 9b7d6d3. The second pins today's surface so a later change is deliberate.

The input schema is normalized as in test_run_command_surface.py: the JSON
form of an optional parameter depends on the Python version.

When search_text's surface changes on purpose, update
SEARCH_TEXT_SURFACE_SHA256 in the same change and say why in the commit.
"""

import asyncio
import copy
import hashlib
import json
from collections.abc import Iterator

from fastmcp import Client

from binnacle import server

SEARCH_TEXT_SURFACE_SHA256 = (
    "bd6f6e576567dad6fd759fac233667aa4b6089d546b90079832fa4761739848a"
)
MASTER_9B7D6D3_SURFACE_SHA256 = (
    "681c1bfe93b9c62777f0a547b01c7727f4cedf420b00f4711b97d7826c831b8b"
)
DESCRIPTION = (
    "Search repository content. Normal regex search replaces grep -rn;\n"
    "names_only replaces grep -c; line_numbers supplies grep -n style context.\n"
    "Prefer this over grep in run_command."
)
PATTERN_DESCRIPTION = "Regex (Rust syntax). Use fixed_strings for literal text."
REMOVED_DESCRIPTION_TEXT = (
    " When the implementation location is\n"
    "unknown, use ``@context <query>`` with ``path`` set to the Git worktree\n"
    "root, then verify/narrow with exact search as needed."
)
REMOVED_PATTERN_TEXT = (
    ", or `@context <query>` for indexed repository discovery when path is"
    " the Git worktree root"
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

    tool = next(t for t in asyncio.run(go()) if t.name == "search_text")
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


def _digest(surface: dict) -> str:
    return hashlib.sha256(json.dumps(surface, sort_keys=True).encode()).hexdigest()


def test_surface_is_master_minus_the_removed_text():
    surface = _surface()
    assert surface["description"] == DESCRIPTION
    pattern = surface["input"]["properties"]["pattern"]
    assert pattern["description"] == PATTERN_DESCRIPTION

    restored = copy.deepcopy(surface)
    restored["description"] = DESCRIPTION + REMOVED_DESCRIPTION_TEXT
    restored["input"]["properties"]["pattern"]["description"] = (
        "Regex (Rust syntax)" + REMOVED_PATTERN_TEXT + "."
        " Use fixed_strings for literal text."
    )
    assert _digest(restored) == MASTER_9B7D6D3_SURFACE_SHA256


def test_search_text_surface_is_pinned():
    assert _digest(_surface()) == SEARCH_TEXT_SURFACE_SHA256


def test_no_tool_or_instruction_mentions_the_removed_mode():
    async def go():
        async with Client(server.mcp) as c:
            return await c.list_tools()

    served = json.dumps([t.model_dump(mode="json") for t in asyncio.run(go())])
    for text in (served, server.mcp.instructions or ""):
        assert "@context" not in text
        assert "indexed repository discovery" not in text
