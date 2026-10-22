"""P2.7 authenticated HTTP JSON-RPC mount/discovery policy (private QA)."""

from __future__ import annotations

import asyncio
import json

import httpx2
import pytest

from binnacle.application import create_application
from binnacle.features.development_intelligence.lsp_preview_server import PREVIEW_NAME
from tests.command_support import MemoryCommands
from tests.integration.test_lsp_p27_fastmcp_mount import (
    BASE_TOOL_NAMES,
    enable_private_feature,
)

pytest_plugins = ("tests.integration.test_lsp_p27_fastmcp_mount",)

HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def as_json(body: str):
    for line in body.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return json.loads(body)


async def start_session(client, *, name: str):
    initial = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": name, "version": "0"},
            },
        },
        headers={**HEADERS, "Authorization": "Bearer private-p27-test-token"},
    )
    assert initial.status_code == 200, initial.text[:300]
    session = initial.headers.get("mcp-session-id")
    assert session
    headers = {
        **HEADERS,
        "Authorization": "Bearer private-p27-test-token",
        "mcp-session-id": session,
    }
    notification = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=headers,
    )
    assert notification.status_code == 202, notification.text[:300]
    return headers


async def call_json(client, headers, method, payload, *, id: int):
    resp = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": id, "method": method, "params": payload},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text[:300]
    return as_json(resp.text)


@pytest.mark.asyncio
async def test_http_default_disabled_never_exposes_preview(mcp_settings):
    settings, _root, source = mcp_settings
    enable_private_feature(settings)
    # Despite explicit feature settings, production does NOT set private gate.
    app = create_application(
        settings=settings, token="private-p27-test-token", backend=MemoryCommands("qa")
    ).http_app()
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://qa"
        ) as http,
    ):
        auth_bad = await http.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 2, "params": {}},
            headers=HEADERS,
        )
        assert auth_bad.status_code == 401
        headers = await start_session(http, name="internal-qa-client")
        listing = await call_json(http, headers, "tools/list", {}, id=2)
        assert [tool["name"] for tool in listing["result"]["tools"]] == BASE_TOOL_NAMES
        attempted = await call_json(
            http,
            headers,
            "tools/call",
            {
                "name": PREVIEW_NAME,
                "arguments": {
                    "source_file": str(source),
                    "line": 2,
                    "column": 10,
                    "expected_symbol": "greet",
                },
            },
            id=3,
        )
        assert attempted.get("error") or attempted["result"].get("isError")


@pytest.mark.asyncio
async def test_http_explicit_private_root_still_honors_chatgpt_allowlist(mcp_settings):
    settings, _root, source = mcp_settings
    enable_private_feature(settings)
    app = create_application(
        settings=settings,
        token="private-p27-test-token",
        backend=MemoryCommands("qa"),
        _private_lsp_preview_gate=True,
    ).http_app()
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://qa"
        ) as http,
    ):
        chat_headers = await start_session(http, name="openai-mcp(ChatGPT)")
        listing = await call_json(http, chat_headers, "tools/list", {}, id=2)
        chat_tools = [item["name"] for item in listing["result"]["tools"]]
        assert chat_tools == [
            "read_file",
            "list_files",
            "search_text",
            "run_command",
            "job_status",
            "stop_job",
        ]
        assert PREVIEW_NAME not in chat_tools
        discovered = await call_json(http, chat_headers, "server/discover", {}, id=8)
        assert PREVIEW_NAME not in json.dumps(discovered)
        denied = await call_json(
            http,
            chat_headers,
            "tools/call",
            {
                "name": PREVIEW_NAME,
                "arguments": {
                    "source_file": str(source),
                    "line": 2,
                    "column": 10,
                    "expected_symbol": "greet",
                },
            },
            id=3,
        )
        assert denied.get("error") or denied["result"].get("isError")


@pytest.mark.asyncio
async def test_http_explicit_private_client_discovers_review_only_tool(mcp_settings):
    settings, _root, _source = mcp_settings
    enable_private_feature(settings)
    app = create_application(
        settings=settings,
        token="private-p27-test-token",
        backend=MemoryCommands("qa"),
        _private_lsp_preview_gate=True,
    ).http_app()
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://qa"
        ) as http,
    ):
        headers = await start_session(http, name="review-qa-client")
        listing = await call_json(http, headers, "tools/list", {}, id=2)
        assert [tool["name"] for tool in listing["result"]["tools"]] == [
            *BASE_TOOL_NAMES,
            PREVIEW_NAME,
        ]


@pytest.mark.asyncio
async def test_http_real_pyright_reuses_pid_and_reaps_on_asgi_shutdown(mcp_settings):
    import os
    from pathlib import Path

    from binnacle.features.development_intelligence.lsp_preview_server import (
        create_private_lsp_preview_server,
    )

    if os.getenv("BINNACLE_PATCHED_MULTILSPY_QA") != "1":
        pytest.skip("Real Pyright HTTP preview requires explicit private opt-in")
    binary = os.getenv("PYRIGHT_LSP_TEST_BIN")
    assert binary and Path(binary).is_absolute() and Path(binary).is_file()
    settings, root, source = mcp_settings
    enable_private_feature(settings, executable=binary)
    children = []

    def capture_child(**kwargs):
        child = create_private_lsp_preview_server(**kwargs)
        children.append(child)
        return child

    app = create_application(
        settings=settings,
        token="private-p27-test-token",
        backend=MemoryCommands("qa"),
        _private_lsp_preview_gate=True,
        _private_lsp_preview_factory=capture_child,
    ).http_app()
    assert len(children) == 1
    life = children[0]._private_preview_lifespan
    assert life.active is None
    process = None
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://qa"
        ) as http,
    ):
        assert life.active is not None and life.active.resident_count == 0
        headers = await start_session(http, name="review-qa-client")
        listing = await call_json(http, headers, "tools/list", {}, id=2)
        assert PREVIEW_NAME in [tool["name"] for tool in listing["result"]["tools"]]
        parameters = {
            "name": PREVIEW_NAME,
            "arguments": {
                "source_file": str(source),
                "line": 2,
                "column": 10,
                "expected_symbol": "greet",
            },
        }
        first = await call_json(http, headers, "tools/call", parameters, id=3)
        assert first["result"].get("isError") is not True
        assert first["result"]["structuredContent"]["locations"][0] == {
            "relative_path": "lib.py",
            "range": {
                "start": {"line": 0, "character": 4},
                "end": {"line": 0, "character": 9},
            },
        }
        manager = life.active
        assert manager.resident_count == 1
        (entry,) = manager._entries.values()
        process = entry.owner._server.server.process
        assert process and process.returncode is None
        original_pid = process.pid
        second = await call_json(http, headers, "tools/call", parameters, id=4)
        assert (
            second["result"]["structuredContent"]
            == first["result"]["structuredContent"]
        )
        assert entry.owner._server.server.process.pid == original_pid
        assert manager.resident_count == 1
        # Multiple HTTP RPCs in the same authenticated MCP session must join
        # one resident process, even though P2.5 serializes document I/O.
        parallel = await asyncio.gather(
            *(
                call_json(http, headers, "tools/call", parameters, id=100 + i)
                for i in range(6)
            )
        )
        assert all(
            answer["result"]["structuredContent"]
            == first["result"]["structuredContent"]
            for answer in parallel
        )
        assert manager.resident_count == 1
        assert entry.owner._server.server.process.pid == original_pid
        # Root middleware and transport must never echo hostile path metadata.
        denied = await call_json(
            http,
            headers,
            "tools/call",
            {
                "name": PREVIEW_NAME,
                "arguments": {
                    "source_file": "/PRIVATE/fake-host-secret.py",
                    "line": 1,
                    "column": 1,
                    "expected_symbol": "password",
                },
            },
            id=5,
        )
        assert denied.get("error") or denied["result"].get("isError")
        assert "/PRIVATE/fake-host-secret.py" not in json.dumps(denied)
    assert life.active is None and life.closed == 1
    assert life.last_close.instances_stopped == 1
    assert life.last_close.cleanup_unverified is False
    assert process is not None and process.returncode is not None
    assert (root / "lib.py").read_text().startswith("def greet")


@pytest.mark.asyncio
async def test_enabled_http_root_reverts_to_disabled_on_new_factory(mcp_settings):
    settings, _root, _source = mcp_settings
    enable_private_feature(settings)
    enabled = create_application(
        settings=settings,
        token="private-p27-test-token",
        backend=MemoryCommands("qa"),
        _private_lsp_preview_gate=True,
    ).http_app()
    async with (
        enabled.router.lifespan_context(enabled),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=enabled), base_url="http://qa"
        ) as http,
    ):
        headers = await start_session(http, name="review-qa-client")
        listing = await call_json(http, headers, "tools/list", {}, id=2)
        assert PREVIEW_NAME in [x["name"] for x in listing["result"]["tools"]]
    settings.development_intelligence.enabled = False
    settings.development_intelligence.discovery_enabled = False
    disabled = create_application(
        settings=settings,
        token="private-p27-test-token",
        backend=MemoryCommands("qa"),
        _private_lsp_preview_gate=True,
    ).http_app()
    async with (
        disabled.router.lifespan_context(disabled),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=disabled), base_url="http://qa"
        ) as http,
    ):
        headers = await start_session(http, name="review-qa-client")
        listing = await call_json(http, headers, "tools/list", {}, id=2)
        assert [x["name"] for x in listing["result"]["tools"]] == BASE_TOOL_NAMES


@pytest.mark.asyncio
@pytest.mark.parametrize("symbol", ["reject", "timeout", "permission", "malformed"])
async def test_parent_http_never_leaks_private_path_from_child_failures(
    mcp_settings, symbol
):
    from binnacle.features.development_intelligence.lsp_preview_server import (
        create_private_lsp_preview_server,
    )
    from tests.unit.core.test_lsp_p27_child_lifespan import FakeResidentManager

    settings, _root, source = mcp_settings
    enable_private_feature(settings)
    created = []

    def private_child(**kwargs):
        return create_private_lsp_preview_server(
            **kwargs,
            manager_factory=lambda s, r: FakeResidentManager(created, s, r),
        )

    app = create_application(
        settings=settings,
        token="private-p27-test-token",
        backend=MemoryCommands("qa"),
        _private_lsp_preview_gate=True,
        _private_lsp_preview_factory=private_child,
    ).http_app()
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://qa"
        ) as http,
    ):
        headers = await start_session(http, name="review-qa-client")
        answer = await call_json(
            http,
            headers,
            "tools/call",
            {
                "name": PREVIEW_NAME,
                "arguments": {
                    "source_file": str(source),
                    "line": 2,
                    "column": 10,
                    "expected_symbol": symbol,
                },
            },
            id=30,
        )
        assert answer.get("error") or answer["result"].get("isError")
        serialized = json.dumps(answer)
        assert "/PRIVATE/" not in serialized
        assert "secret.py" not in serialized
        assert "private data" not in serialized
        assert str(source) not in serialized
    assert len(created) == 1 and created[0].closed
