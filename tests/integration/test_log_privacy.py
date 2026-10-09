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
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert secret not in logged
    assert "event=job_start" in logged
    assert f"workdir=pathhash:{path_digest(str(tmp_path))}" in logged
    assert "command='[redacted]'" in logged
    assert "event=tool_call" in logged and "event=request_start" in logged
    assert "error=[redacted]" in logged


def test_per_request_smoke_proof_correlates_actual_middleware_without_payload_leak(
    caplog,
):
    from binnacle.observability.log_safety import SMOKE_CORRELATION_FIELD

    proof = "a" * 32
    secret = "SYNTHETIC_METADATA_NEVER_LOG_20261009"

    async def go(mode):
        async with Client(mcp, mode=mode, cache=False) as client:
            result = await client.call_tool(
                "list_files",
                {"path": "/tmp", "max_results": 1},
                meta={SMOKE_CORRELATION_FIELD: proof},
                raise_on_error=False,
            )
            assert not result.is_error
            result = await client.call_tool(
                "list_files",
                {"path": "/tmp", "max_results": 1},
                meta={SMOKE_CORRELATION_FIELD: secret},
                raise_on_error=False,
            )
            assert not result.is_error

    with caplog.at_level(logging.INFO):
        for mode in ("2026-07-28", "legacy"):
            asyncio.run(go(mode))

    rows = [record.getMessage() for record in caplog.records]
    calls = [x for x in rows if "event=tool_call " in x]
    results = [x for x in rows if "event=tool_result " in x]
    assert len(calls) == len(results) == 4
    assert sum("smoke=" + proof in row for row in calls) == 2
    assert sum("smoke=" + proof in row for row in results) == 2
    assert secret not in "\n".join(rows)
    assert all("smoke=" not in row for row in calls if "smoke=" + proof not in row)


def test_http_transport_smoke_proof_is_visible_to_native_middleware(
    caplog, monkeypatch, tmp_path
):
    """Real authenticated HTTP/ASGI transport exercises request.meta handoff."""
    import httpx2
    from fastmcp.client.transports import StreamableHttpTransport

    from binnacle import server
    from binnacle.observability.log_safety import SMOKE_CORRELATION_FIELD

    proof = "c" * 32
    secret = "UNLOGGED_HTTP_MESSAGE_BODY_20261009"
    token_path = tmp_path / "token"
    token_path.write_text("http-acceptance-token")
    monkeypatch.setattr(server, "TOKEN_FILE", token_path)
    app = server.create_server().http_app()

    def factory(**kwargs):
        return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), **kwargs)

    async def go(mode):
        async with app.router.lifespan_context(app):
            transport = StreamableHttpTransport(
                "http://test/mcp",
                auth="http-acceptance-token",
                httpx_client_factory=factory,
            )
            async with Client(transport, mode=mode, cache=False) as client:
                response = await client.call_tool(
                    "list_files",
                    {"path": str(tmp_path), "max_results": 1},
                    meta={SMOKE_CORRELATION_FIELD: proof, "unexpected": secret},
                    raise_on_error=False,
                )
                assert not response.is_error

    with caplog.at_level(logging.INFO):
        for mode in ("2026-07-28", "legacy"):
            asyncio.run(go(mode))

    rows = [entry.getMessage() for entry in caplog.records]
    calls = [row for row in rows if "event=tool_call " in row]
    results = [row for row in rows if "event=tool_result " in row]
    assert len(calls) == len(results) == 2
    assert all(f"smoke={proof}" in row for row in calls + results)
    assert secret not in "\n".join(rows)
