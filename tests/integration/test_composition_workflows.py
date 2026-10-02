"""Real tool workflows through standalone focused FastMCP children."""

import asyncio
import json
import logging

from fastmcp import Client

from binnacle import server
from binnacle.files_server import create_files_server
from binnacle.search_server import create_search_server


def test_files_child_scratch_workflow(tmp_path):
    path = tmp_path / "file.txt"

    async def go():
        async with Client(create_files_server()) as client:
            written = await client.call_tool(
                "write_file", {"path": str(path), "content": "alpha\nbeta\n"}
            )
            assert written.structured_content["action"] == "created"
            read = await client.call_tool("read_file", {"path": str(path)})
            assert read.structured_content["content"] == "alpha\nbeta\n"
            edited = await client.call_tool(
                "edit_file",
                {
                    "path": str(path),
                    "old_string": "beta",
                    "new_string": "gamma",
                },
            )
            assert edited.structured_content["replacements"] == 1
            listed = await client.call_tool("list_files", {"path": str(tmp_path)})
            assert "file.txt" in json.dumps(listed.structured_content)
            failed = await client.call_tool(
                "read_file", {"path": str(tmp_path / "missing")}, raise_on_error=False
            )
            assert failed.is_error

    asyncio.run(go())
    assert path.read_text() == "alpha\ngamma\n"


def test_search_child_result_and_telemetry_parity(tmp_path, caplog):
    (tmp_path / "file.txt").write_text("alpha\nbeta\n")

    async def call(root):
        async with Client(root) as client:
            return await client.call_tool(
                "search_text", {"path": str(tmp_path), "pattern": "alpha"}
            )

    with caplog.at_level(logging.INFO, logger="binnacle.search_text"):
        child = asyncio.run(call(create_search_server()))
        exported = asyncio.run(call(server.mcp))
    assert child.structured_content == exported.structured_content
    assert child.content == exported.content
    assert "file.txt" in json.dumps(child.structured_content)
    dispatch = [
        record.getMessage()
        for record in caplog.records
        if "event=search_dispatch " in record.getMessage()
    ]
    assert len(dispatch) == 2
    assert all("mode=exact" in line for line in dispatch)
    assert "call=- " in dispatch[0]
    assert "call=- " not in dispatch[1]
