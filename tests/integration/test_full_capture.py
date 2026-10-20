"""End-to-end opt-in raw audit capture without changing sanitized journals."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastmcp import Client, FastMCP

from binnacle.config import Settings
from binnacle.config_telemetry import FullCaptureSettings
from binnacle.mcp.identity import ClientIdentity
from binnacle.mcp.logging_setup import attach_logging


def _rows(directory: Path) -> list[dict]:
    files = list(directory.glob("*.jsonl"))
    assert len(files) == 1
    return [json.loads(line) for line in files[0].read_text().splitlines()]


def _server(tmp_path: Path, *, capture: bool) -> FastMCP:
    settings = Settings()
    settings.telemetry.full_capture = FullCaptureSettings(
        enabled=capture, directory=tmp_path / "audit"
    )
    root = FastMCP("full-capture-test")
    attach_logging(root, ClientIdentity(), settings)

    @root.tool
    def sample_tool(payload: str) -> str:
        """Echo large text exactly."""
        return f"returned:{payload}"

    return root


def _invoke(server: FastMCP, text: str, *, invalid: bool = False) -> None:
    async def invoke() -> None:
        async with Client(server) as client:
            await client.list_tools()
            if invalid:
                await client.call_tool(
                    "unknown_tool", {"payload": text}, raise_on_error=False
                )
            else:
                result = await client.call_tool("sample_tool", {"payload": text})
                assert result.content[0].text == "returned:" + text

    asyncio.run(invoke())


def test_disabled_is_privacy_preserving(caplog, tmp_path):
    text = "secret-token-from-user-" + "z" * 1000
    with caplog.at_level(logging.INFO):
        _invoke(_server(tmp_path, capture=False), text)
    assert not (tmp_path / "audit").exists()
    assert text not in caplog.text
    assert "event=tool_result" in caplog.text


def test_enabled_captures_unlimited_requests_results_and_correlation(caplog, tmp_path):
    text = "secret-token-from-user-" + "z" * 3000 + "\nmultiline"
    with caplog.at_level(logging.INFO):
        _invoke(_server(tmp_path, capture=True), text)
    rows = _rows(tmp_path / "audit")
    calls = [r for r in rows if r["event"] == "tool_call"]
    results = [r for r in rows if r["event"] == "tool_result"]
    assert len(calls) == len(results) == 1
    assert calls[0]["arguments"]["payload"] == text
    assert calls[0]["correlation"]["call"] == results[0]["correlation"]["call"]
    assert calls[0]["raw_client"] is not None
    assert results[0]["result"]["content"][0]["text"] == "returned:" + text
    assert any(
        r["event"] == "mcp_request"
        and "tools/call" == r["method"]
        and r["payload"]["arguments"]["payload"] == text
        for r in rows
    )
    assert any(
        r["event"] == "mcp_response" and r["method"] == "tools/call" for r in rows
    )
    assert any(
        row["event"] == "mcp_response"
        and row["method"] == "tools/list"
        and any(tool["name"] == "sample_tool" for tool in row["result"])
        for row in rows
    )
    assert "event=full_capture_error" not in caplog.text
    assert text not in caplog.text
    assert "returned:" + text not in caplog.text
    assert (tmp_path / "audit").stat().st_mode & 0o077 == 0
    assert next((tmp_path / "audit").glob("*.jsonl")).stat().st_mode & 0o077 == 0


def test_errors_are_available_privately_not_in_journal(caplog, tmp_path):
    private = "private-value-from-unknown-tool"
    with caplog.at_level(logging.INFO):
        _invoke(_server(tmp_path, capture=True), private, invalid=True)
    rows = _rows(tmp_path / "audit")
    assert any(r["event"] == "mcp_request" for r in rows)
    assert any(r["event"] in {"tool_error", "mcp_error"} for r in rows)
    assert private not in caplog.text


def test_full_capture_other_mcp_catalogues(tmp_path, caplog):
    server = _server(tmp_path, capture=True)

    @server.resource("note://one")
    def example_resource() -> str:
        """An inspectable test resource."""
        return "resource-text"

    @server.prompt()
    def example_prompt() -> str:
        """An inspectable test prompt."""
        return "prompt-text"

    async def run() -> None:
        async with Client(server) as client:
            resources = await client.list_resources()
            prompts = await client.list_prompts()
            assert resources and prompts

    with caplog.at_level(logging.INFO):
        asyncio.run(run())
    rows = _rows(tmp_path / "audit")
    assert any(
        row["event"] == "mcp_response" and row["method"] == "resources/list"
        for row in rows
    )
    assert any(
        row["event"] == "mcp_response" and row["method"] == "prompts/list"
        for row in rows
    )
    assert "event=full_capture_error" not in caplog.text
