"""Real tool workflows through standalone focused FastMCP children."""

import asyncio
import json
import logging

from fastmcp import Client

from binnacle import server
from binnacle.features.commands import jobs
from binnacle.features.commands.commands_server import create_commands_server
from binnacle.features.files.files_server import create_files_server
from binnacle.features.search.search_server import create_search_server
from tests.integration.job_test_support import stop


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


def test_commands_child_sync_background_cursor_and_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(jobs, "OWNER_MODE", "embedded")

    async def go():
        async with Client(create_commands_server()) as client:
            sync = await client.call_tool(
                "run_command",
                {
                    "command": "printf composition-sync",
                    "workdir": str(tmp_path),
                    "wait_seconds": 5,
                },
            )
            payload = sync.structured_content
            assert payload["state"] == "exited" and payload["exit_code"] == 0
            assert payload["background_job"] is False
            assert payload["output"] == "composition-sync"
            status = await client.call_tool(
                "job_status",
                {
                    "job_id": payload["job_id"],
                    "cursor": "start",
                },
            )
            cursor = status.structured_content
            assert cursor["log_delta"] == "composition-sync"
            assert cursor["delta_start"] == 0 and cursor["delta_end"] == 16
            assert "log_tail" not in cursor
            again = await client.call_tool(
                "job_status",
                {
                    "job_id": payload["job_id"],
                    "cursor": cursor["next_cursor"],
                },
            )
            assert again.structured_content["log_delta"] == ""
            started = await client.call_tool(
                "run_command",
                {
                    "command": "sleep 30",
                    "workdir": str(tmp_path),
                    "background": True,
                },
            )
            running = started.structured_content
            assert running["state"] == "running" and running["background_job"] is True
            active = await client.call_tool("job_status", {"job_id": running["job_id"]})
            assert active.structured_content["exit_code"] is None
            listing = await client.call_tool("job_status", {})
            assert any(
                row["job_id"] == running["job_id"]
                for row in listing.structured_content["jobs"]
            )
            stopped = await client.call_tool("stop_job", {"job_id": running["job_id"]})
            assert stopped.structured_content["state"] == "exited"
            assert stopped.structured_content["signal"] == 15
            failed = await client.call_tool(
                "stop_job", {"job_id": "missing"}, raise_on_error=False
            )
            assert failed.is_error

    try:
        asyncio.run(go())
    finally:
        # Covers failures before an MCP result exposes its newly created job ID.
        for state in jobs.list_jobs():
            if state["state"] == "running":
                assert stop(state["job_id"])["state"] == "exited"
