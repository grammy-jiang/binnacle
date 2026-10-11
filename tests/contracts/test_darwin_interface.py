"""CR1A-02 permits one Darwin description change; all eight schemas stay pinned."""

import asyncio
import json
from pathlib import Path

from fastmcp import Client

from binnacle.application import create_application
from binnacle.config import RootsSettings, Settings
from binnacle.features.commands.restricted_backend import RestrictedCommandBackend


def test_native_wire_schema_preserves_v101_with_declared_description_exception(
    tmp_path,
):
    baseline = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "docs/os-independent-stage1-evidence/os0-raw-mcp-surface.json"
        ).read_text()
    )["profile_surfaces"]["default"]
    root = create_application(
        settings=Settings(roots=RootsSettings(default_root=tmp_path, extra_roots=())),
        token="test",
        backend=RestrictedCommandBackend(),
    )

    async def inspect():
        async with Client(root) as client:
            return await client.list_tools(), client.instructions

    tools, instructions = asyncio.run(inspect())
    actual = [tool.model_dump(mode="json", by_alias=True) for tool in tools]
    assert instructions == baseline["instructions"]
    assert len(actual) == 8
    native = next(tool for tool in actual if tool["name"] == "run_command")
    description = native["description"].lower()
    assert (
        "background processes are terminated when the command finishes" in description
    )
    assert "processes that start a new session (setsid) are not tracked" in description
    assert "unavailable pending r1 + cr1" in description
    original = next(tool for tool in baseline["tools"] if tool["name"] == "run_command")
    native["description"] = original["description"]
    assert actual == baseline["tools"]
