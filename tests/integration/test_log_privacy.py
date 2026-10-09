"""End-to-end privacy contract across the real mounted MCP middleware."""

import asyncio
import logging

from fastmcp import Client

from binnacle.features.commands import jobs
from binnacle.observability.log_safety import path_digest
from binnacle.server import mcp


def invoke(tool: str, arguments: dict):
    async def go():
        async with Client(mcp, cache=False) as client:
            return await client.call_tool(tool, arguments, raise_on_error=False)

    return asyncio.run(go())


def test_journal_does_not_include_user_supplied_secrets(caplog, monkeypatch, tmp_path):
    """Both root request logs and durable-job logs must redact free-form input."""
    secret = "SYNTHETIC_PRIVATE_VALUE_20261009"
    file = tmp_path / ("private-" + secret + ".txt")
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    with caplog.at_level(logging.INFO):
        written = invoke("write_file", {"path": str(file), "content": secret})
        command_result = invoke(
            "run_command",
            {
                "command": f"printf '{secret}' >/dev/null",
                "workdir": str(tmp_path),
                "stdin": secret,
            },
        )
        failure = invoke("read_file", {"path": str(tmp_path / secret)})
        invoke("no_such_tool_" + secret, {})

    assert not written.is_error and file.read_text() == secret
    assert not command_result.is_error
    assert failure.is_error
    logged = "\\n".join(record.getMessage() for record in caplog.records)
    assert secret not in logged
    assert "event=job_start" in logged
    assert f"workdir=pathhash:{path_digest(str(tmp_path))}" in logged
    assert "command='[redacted]'" in logged
    assert "event=tool_call" in logged and "event=request_start" in logged
    assert "error=[redacted]" in logged
