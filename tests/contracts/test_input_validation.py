"""MCP input validation as a strict client experiences it."""

import asyncio

import pytest
from fastmcp import Client

from binnacle import server


def call(name: str, arguments: dict):
    async def run():
        async with Client(server.mcp) as client:
            return await client.call_tool(name, arguments, raise_on_error=False)

    return asyncio.run(run())


def text_of(result) -> str:
    return "\n".join(getattr(part, "text", "") for part in result.content)


def list_tools():
    async def run():
        async with Client(server.mcp) as client:
            return await client.list_tools()

    return asyncio.run(run())


def test_every_tool_rejects_schema_unknown_arguments():
    for tool in list_tools():
        assert tool.input_schema.get("additionalProperties") is False, tool.name


@pytest.mark.parametrize(
    ("tool", "arguments", "field"),
    [
        ("read_file", {}, "path"),
        ("search_text", {}, "pattern"),
        ("edit_file", {}, "path"),
        ("write_file", {}, "path"),
        ("run_command", {}, "command"),
        ("stop_job", {}, "job_id"),
    ],
)
def test_missing_required_arguments_are_tool_errors(tool, arguments, field):
    result = call(tool, arguments)

    assert result.is_error
    assert field in text_of(result)


@pytest.mark.parametrize(
    ("tool", "arguments", "field"),
    [
        ("read_file", {"path": "/tmp/no-file", "start_line": 0}, "start_line"),
        ("read_file", {"path": "/tmp/no-file", "end_line": 0}, "end_line"),
        ("list_files", {"path": "/tmp", "max_results": 0}, "max_results"),
        ("list_files", {"path": "/tmp", "max_results": 2001}, "max_results"),
        (
            "search_text",
            {"path": "/tmp", "pattern": "x", "max_results": 0},
            "max_results",
        ),
        (
            "search_text",
            {"path": "/tmp", "pattern": "x", "max_results": 1001},
            "max_results",
        ),
        (
            "run_command",
            {"command": "true", "workdir": "/tmp", "wait_seconds": 0},
            "wait_seconds",
        ),
        (
            "run_command",
            {"command": "true", "workdir": "/tmp", "wait_seconds": 51},
            "wait_seconds",
        ),
        ("job_status", {"tail_lines": 0}, "tail_lines"),
        ("job_status", {"wait_seconds": 51}, "wait_seconds"),
    ],
)
def test_numeric_schema_bounds_fail_before_tool_execution(tool, arguments, field):
    result = call(tool, arguments)

    assert result.is_error
    assert field in text_of(result)


def test_unknown_argument_is_rejected_at_protocol_boundary():
    result = call(
        "read_file",
        {"path": "/tmp/does-not-matter", "unexpected_argument": True},
    )

    assert result.is_error
    text = text_of(result)
    assert "unexpected_argument" in text
    assert "Unexpected keyword argument" in text


def test_wrong_scalar_type_is_rejected():
    result = call("list_files", {"path": "/tmp", "max_results": "many"})

    assert result.is_error
    assert "max_results" in text_of(result)
