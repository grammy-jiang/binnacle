"""Real tool workflows through standalone focused FastMCP children."""

import asyncio
import json

from fastmcp import Client

from binnacle.files_server import create_files_server


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
