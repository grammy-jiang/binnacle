"""Finite modern/legacy MCP revision dispatch integration tests."""

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest
from tests.support import running_raw_http_client

from binnacle.application import BinnacleApplication
from binnacle.contracts import EXPECTED_REVISIONS

ACCEPT = "application/json, text/event-stream"
PROTOCOL_META = "io.modelcontextprotocol/protocolVersion"
CLIENT_INFO_META = "io.modelcontextprotocol/clientInfo"
CLIENT_CAPABILITIES_META = "io.modelcontextprotocol/clientCapabilities"


def _jsonrpc(response: httpx2.Response) -> dict[str, Any]:
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        data_line = next(line for line in response.text.splitlines() if line.startswith("data: "))
        value = json.loads(data_line.removeprefix("data: "))
    else:
        value = response.json()
    assert isinstance(value, dict)
    return value


def _modern_body(
    method: str,
    params: dict[str, Any] | None = None,
    *,
    revision: str = "2026-07-28",
    request_id: int = 1,
) -> dict[str, Any]:
    values = dict(params or {})
    values["_meta"] = {
        PROTOCOL_META: revision,
        CLIENT_INFO_META: {"name": "binnacle-test", "version": "1"},
        CLIENT_CAPABILITIES_META: {},
    }
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": values,
    }


def _modern_headers(
    method: str,
    *,
    revision: str = "2026-07-28",
    name: str | None = None,
) -> dict[str, str]:
    headers = {
        "accept": ACCEPT,
        "MCP-Protocol-Version": revision,
        "Mcp-Method": method,
    }
    if name is not None:
        headers["Mcp-Name"] = name
    return headers


async def _legacy_session(client: httpx2.AsyncClient, revision: str) -> str:
    response = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": revision,
                "capabilities": {},
                "clientInfo": {"name": "binnacle-test", "version": "1"},
            },
        },
        headers={"accept": ACCEPT, "MCP-Protocol-Version": revision},
    )
    assert response.status_code == 200
    assert _jsonrpc(response)["result"]["protocolVersion"] == revision
    session_id = response.headers["mcp-session-id"]
    initialized = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={
            "accept": ACCEPT,
            "MCP-Protocol-Version": revision,
            "Mcp-Session-Id": session_id,
        },
    )
    assert initialized.status_code == 202
    return session_id


@pytest.mark.anyio
async def test_target_revision_is_sessionless_and_complete(
    phase2_application: BinnacleApplication,
) -> None:
    async with running_raw_http_client(phase2_application) as client:
        listed = await client.post(
            "/mcp",
            json=_modern_body("tools/list"),
            headers=_modern_headers("tools/list"),
        )
        called = await client.post(
            "/mcp",
            json=_modern_body(
                "tools/call",
                {"name": "binnacle_probe", "arguments": {}},
                request_id=2,
            ),
            headers=_modern_headers("tools/call", name="binnacle_probe"),
        )

    assert listed.status_code == 200
    assert "mcp-session-id" not in listed.headers
    assert len(_jsonrpc(listed)["result"]["tools"]) == 5
    result = _jsonrpc(called)["result"]
    assert result["resultType"] == "complete"
    assert result["structuredContent"]["data"]["protocol_era"] == "modern"


@pytest.mark.anyio
@pytest.mark.parametrize("revision", EXPECTED_REVISIONS[1:])
async def test_each_legacy_revision_negotiates_lists_and_calls(
    phase2_application: BinnacleApplication,
    revision: str,
) -> None:
    async with running_raw_http_client(phase2_application) as client:
        session_id = await _legacy_session(client, revision)
        headers = {
            "accept": ACCEPT,
            "MCP-Protocol-Version": revision,
            "Mcp-Session-Id": session_id,
        }
        listed = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers=headers,
        )
        called = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "binnacle_probe", "arguments": {}},
            },
            headers=headers,
        )

    assert len(_jsonrpc(listed)["result"]["tools"]) == 5
    result = _jsonrpc(called)["result"]
    assert "resultType" not in result
    assert result["structuredContent"]["data"]["protocol_revision"] == revision
    assert result["structuredContent"]["data"]["protocol_era"] == "legacy"


@pytest.mark.anyio
async def test_unsupported_2024_revision_reaches_revision_guard(
    phase2_application: BinnacleApplication,
) -> None:
    revision = "2024-11-05"
    async with running_raw_http_client(phase2_application) as client:
        response = await client.post(
            "/mcp",
            json=_modern_body("tools/list", revision=revision),
            headers=_modern_headers("tools/list", revision=revision),
        )

    assert response.status_code == 400
    error = _jsonrpc(response)["error"]
    assert error["code"] == -32021


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("revision", "message"),
    [
        (None, "The request is missing MCP-Protocol-Version."),
        ("2024-11-05", "The request does not declare a reviewed protocol revision."),
    ],
)
async def test_sessionless_request_requires_a_reviewed_revision_header(
    phase2_application: BinnacleApplication,
    revision: str | None,
    message: str,
) -> None:
    headers = {"accept": ACCEPT}
    if revision is not None:
        headers["MCP-Protocol-Version"] = revision
    async with running_raw_http_client(phase2_application) as client:
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 99, "method": "tools/list", "params": {}},
            headers=headers,
        )

    assert response.status_code == 400
    assert _jsonrpc(response)["error"] == {
        "code": -32021,
        "message": message,
        "data": {
            "code": "unsupported_protocol_version",
            "supported": list(EXPECTED_REVISIONS),
        },
    }


@pytest.mark.anyio
async def test_target_request_requires_version_header(
    phase2_application: BinnacleApplication,
) -> None:
    async with running_raw_http_client(phase2_application) as client:
        response = await client.post(
            "/mcp",
            json=_modern_body("tools/list"),
            headers={"accept": ACCEPT, "Mcp-Method": "tools/list"},
        )

    assert response.status_code == 400
    assert _jsonrpc(response)["error"] == {
        "code": -32021,
        "message": "The target request is missing MCP-Protocol-Version.",
        "data": {
            "code": "unsupported_protocol_version",
            "supported": list(EXPECTED_REVISIONS),
        },
    }


@pytest.mark.anyio
async def test_duplicate_target_routing_header_is_rejected(
    phase2_application: BinnacleApplication,
) -> None:
    headers = [
        ("accept", ACCEPT),
        ("MCP-Protocol-Version", "2026-07-28"),
        ("MCP-Protocol-Version", "2026-07-28"),
        ("Mcp-Method", "tools/list"),
    ]
    async with running_raw_http_client(phase2_application) as client:
        response = await client.post(
            "/mcp",
            json=_modern_body("tools/list"),
            headers=headers,
        )

    assert response.status_code == 400
    assert _jsonrpc(response)["error"]["data"]["code"] == "protocol_header_mismatch"


@pytest.mark.anyio
async def test_cross_era_modern_envelope_is_rejected(
    phase2_application: BinnacleApplication,
) -> None:
    revision = "2025-11-25"
    async with running_raw_http_client(phase2_application) as client:
        response = await client.post(
            "/mcp",
            json=_modern_body("tools/list", revision=revision),
            headers=_modern_headers("tools/list", revision=revision),
        )

    assert response.status_code == 400
    assert _jsonrpc(response)["error"]["code"] == -32021


@pytest.mark.anyio
async def test_target_shaped_initialize_cannot_create_a_legacy_session(
    phase2_application: BinnacleApplication,
) -> None:
    async with running_raw_http_client(phase2_application) as client:
        response = await client.post(
            "/mcp",
            json=_modern_body(
                "initialize",
                {
                    "protocolVersion": EXPECTED_REVISIONS[1],
                    "capabilities": {},
                    "clientInfo": {"name": "binnacle-test", "version": "1"},
                },
            ),
            headers=_modern_headers("initialize"),
        )

    assert response.status_code == 400
    assert "mcp-session-id" not in response.headers
    assert _jsonrpc(response)["error"] == {
        "code": -32021,
        "message": "The reviewed target revision does not support initialize.",
        "data": {
            "code": "unsupported_protocol_version",
            "supported": list(EXPECTED_REVISIONS),
        },
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("header_method", "header_name"),
    [
        ("resources/list", "binnacle_probe"),
        ("tools/call", "system_inspect"),
    ],
)
async def test_target_routing_header_mismatch_is_rejected_before_tool_dispatch(
    phase2_application: BinnacleApplication,
    header_method: str,
    header_name: str,
) -> None:
    async with running_raw_http_client(phase2_application) as client:
        response = await client.post(
            "/mcp",
            json=_modern_body(
                "tools/call",
                {"name": "binnacle_probe", "arguments": {}},
            ),
            headers=_modern_headers(header_method, name=header_name),
        )

    assert response.status_code == 400
    assert _jsonrpc(response)["error"]["code"] == -32020


@pytest.mark.anyio
async def test_target_revision_rejects_legacy_session_header(
    phase2_application: BinnacleApplication,
) -> None:
    headers = _modern_headers("tools/list")
    headers["Mcp-Session-Id"] = "legacy-session"
    async with running_raw_http_client(phase2_application) as client:
        response = await client.post(
            "/mcp",
            json=_modern_body("tools/list"),
            headers=headers,
        )

    assert response.status_code == 400
    assert "session" in response.text.lower()


@pytest.mark.anyio
async def test_legacy_session_rejects_wrong_post_initialize_version(
    phase2_application: BinnacleApplication,
) -> None:
    async with running_raw_http_client(phase2_application) as client:
        session_id = await _legacy_session(client, "2025-11-25")
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers={
                "accept": ACCEPT,
                "MCP-Protocol-Version": "2025-06-18",
                "Mcp-Session-Id": session_id,
            },
        )

    assert response.status_code == 200
    assert _jsonrpc(response)["error"] == {
        "code": -32020,
        "message": "MCP-Protocol-Version does not match the negotiated legacy session.",
    }


@pytest.mark.anyio
async def test_legacy_session_requires_post_initialize_version(
    phase2_application: BinnacleApplication,
) -> None:
    async with running_raw_http_client(phase2_application) as client:
        session_id = await _legacy_session(client, "2025-11-25")
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers={"accept": ACCEPT, "Mcp-Session-Id": session_id},
        )

    assert response.status_code == 400
    assert _jsonrpc(response)["error"]["code"] == -32021


@pytest.mark.anyio
async def test_disabled_tasks_request_reaches_method_dispatch(
    phase2_application: BinnacleApplication,
) -> None:
    async with running_raw_http_client(phase2_application) as client:
        response = await client.post(
            "/mcp",
            json=_modern_body("tasks/list"),
            headers=_modern_headers("tasks/list"),
        )

    assert response.status_code == 404
    assert _jsonrpc(response)["error"]["code"] == -32601
