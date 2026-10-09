"""The presentation Transform preserves components, multiplicity, and metadata."""

import asyncio
from collections import Counter

import pytest
from fastmcp.tools.base import Tool
from hypothesis import example, given, settings
from hypothesis import strategies as st
from mcp.types import ToolAnnotations

from binnacle.mcp.tool_order import PublicToolOrder

# Independent of the production rank table; changing one must fail this contract.
ORDER = [
    "read_file",
    "list_files",
    "search_text",
    "edit_file",
    "write_file",
    "run_command",
    "job_status",
    "stop_job",
]


def component(name, index):
    return Tool(
        name=name,
        description=f"unchanged {index}",
        parameters={"type": "object", "properties": {}},
        output_schema={"type": "object"},
        annotations=ToolAnnotations(read_only_hint=True),
        meta={"probe": index},
        tags={"probe"},
        title=f"Title {index}",
    )


@settings(max_examples=100, deadline=None)
@given(st.lists(st.sampled_from([*ORDER, "unknown_z", "unknown_a"]), max_size=30))
@example([])
@example(["unknown_z", "stop_job", "read_file", "unknown_a", "read_file"])
def test_order_is_stable_lossless_and_idempotent(names):
    tools = [component(name, index) for index, name in enumerate(names)]
    before = [tool.model_dump() for tool in tools]
    original = list(tools)
    ordered = asyncio.run(PublicToolOrder().list_tools(tools))
    expected = [tool for name in ORDER for tool in tools if tool.name == name]
    expected.extend(tool for tool in tools if tool.name not in ORDER)
    assert [id(tool) for tool in ordered] == [id(tool) for tool in expected]
    assert Counter(map(id, ordered)) == Counter(map(id, tools))
    assert tools == original
    assert [tool.model_dump() for tool in tools] == before
    assert asyncio.run(PublicToolOrder().list_tools(ordered)) == ordered


@pytest.mark.parametrize("container", [list, tuple])
def test_repeated_object_and_unknown_relative_order_survive(container):
    unknown, known, other = [component(name, 0) for name in ("z", "read_file", "a")]
    original = container([unknown, known, other, known])
    ordered = asyncio.run(PublicToolOrder().list_tools(original))
    assert [id(tool) for tool in ordered] == [
        id(known),
        id(known),
        id(unknown),
        id(other),
    ]
    assert list(original) == [unknown, known, other, known]
