"""Opt-in read-only smoke tests against the actually deployed Raspberry Pi.

Run explicitly with:

    BINNACLE_LIVE=1 uv run pytest tests/live -q

Nothing in this suite changes services, network state, files, or hardware.
"""

import asyncio
import json
import os
import subprocess

import httpx2
import pytest

from binnacle.config import get_settings

pytestmark = pytest.mark.skipif(
    os.environ.get("BINNACLE_LIVE") != "1",
    reason="set BINNACLE_LIVE=1 to test the deployed host",
)

PROD_UNIT = "binnacle-mcp.service"
DEV_UNIT = "binnacle-mcp-dev.service"


def _unit_state(unit: str) -> str:
    proc = subprocess.run(
        ["systemctl", "--user", "is-active", unit],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return proc.stdout.strip() or "unknown"


def test_exactly_one_binnacle_server_unit_is_active():
    states = {unit: _unit_state(unit) for unit in (PROD_UNIT, DEV_UNIT)}

    assert list(states.values()).count("active") == 1, states


def test_deployed_http_mcp_auth_initialize_and_tools_list():
    settings = get_settings()
    token = (
        settings.auth.token_file.read_text(encoding="utf-8")
        .strip()
        .removeprefix("Bearer ")
        .strip()
    )
    base = f"http://{settings.serve.host}:{settings.serve.port}"
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "binnacle-live-smoke", "version": "1"},
        },
    }

    async def run():
        async with httpx2.AsyncClient(base_url=base, timeout=10) as client:
            init = await client.post("/mcp", json=initialize, headers=headers)
            assert init.status_code == 200, init.text[:300]
            session = init.headers.get("mcp-session-id")
            assert session
            session_headers = {**headers, "mcp-session-id": session}
            initialized = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                },
                headers=session_headers,
            )
            assert initialized.status_code == 202
            tools = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                },
                headers=session_headers,
            )
            assert tools.status_code == 200
            call = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "list_files",
                        "arguments": {"path": "/tmp", "max_results": 1},
                    },
                },
                headers=session_headers,
            )
            assert call.status_code == 200
            return tools.text, call.text

    tools_body, call_body = asyncio.run(run())
    payload = next(
        json.loads(line[5:].strip())
        for line in tools_body.splitlines()
        if line.startswith("data:")
    )
    names = {tool["name"] for tool in payload["result"]["tools"]}
    assert {
        "read_file",
        "list_files",
        "search_text",
        "run_command",
        "job_status",
        "stop_job",
    } <= names
    call = next(
        json.loads(line[5:].strip())
        for line in call_body.splitlines()
        if line.startswith("data:")
    )
    assert call["result"]["isError"] is False
    assert call["result"]["structuredContent"]["count"] <= 1


def test_live_cli_mode_status_is_read_only_and_reports_both_units():
    proc = subprocess.run(
        [os.sys.executable, "-m", "binnacle.cli", "mode", "status"],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )

    assert proc.returncode == 0, proc.stderr
    assert PROD_UNIT in proc.stdout
    assert DEV_UNIT in proc.stdout
