"""Focused tests for MCP request projection, bounds, and diagnostics."""

from __future__ import annotations

import json
from collections.abc import Mapping, MutableMapping
from typing import Any

import pytest
from mcp.shared.exceptions import MCPError

from binnacle.adapters.mcp import (
    ASGIMessage,
    ASGIReceive,
    ASGISend,
    RequestBodyLimitMiddleware,
    RevisionGuardMiddleware,
    _load_handler,
    _model_readable_text,
    _request_from_arguments,
)
from binnacle.domain.mcp import (
    BinnacleProbeRequest,
    CompatibilityReportRequest,
    ProbeErrorCase,
    ProbeErrorRequest,
    ProbeResultFormatsRequest,
    SystemInspectRequest,
)
from binnacle.domain.system import SystemSection


class RecordingASGIApp:
    """Small downstream app that records the replayed request."""

    def __init__(
        self,
        *,
        response_headers: list[tuple[bytes, bytes]] | None = None,
    ) -> None:
        self.calls = 0
        self.received: list[ASGIMessage] = []
        self.response_headers = response_headers or []

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        del scope
        self.calls += 1
        self.received.append(await receive())
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": self.response_headers,
            }
        )
        await send({"type": "http.response.body", "body": b"{}"})


async def _exercise_middleware(
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
    messages: list[ASGIMessage] | None = None,
    max_request_bytes: int = 64,
    method: str = "POST",
    path: str = "/mcp",
    app: RecordingASGIApp | None = None,
) -> tuple[RecordingASGIApp, list[ASGIMessage]]:
    downstream = app or RecordingASGIApp()
    middleware = RequestBodyLimitMiddleware(
        downstream,
        max_request_bytes=max_request_bytes,
    )
    queue = list(messages or [{"type": "http.request", "body": b""}])
    sent: list[ASGIMessage] = []

    async def receive() -> ASGIMessage:
        if queue:
            return queue.pop(0)
        return {"type": "http.disconnect"}

    async def send(message: ASGIMessage) -> None:
        sent.append(message)

    await middleware(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": headers or [],
        },
        receive,
        send,
    )
    return downstream, sent


def _response_json(messages: list[ASGIMessage]) -> dict[str, Any]:
    body = messages[-1].get("body")
    assert isinstance(body, bytes)
    value = json.loads(body)
    assert isinstance(value, dict)
    return value


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_type"),
    [
        ("binnacle_probe", {}, BinnacleProbeRequest),
        ("system_inspect", {}, SystemInspectRequest),
        ("probe_result_formats", {}, ProbeResultFormatsRequest),
        ("probe_error", {"case": "timeout"}, ProbeErrorRequest),
        ("compatibility_report", {}, CompatibilityReportRequest),
    ],
)
def test_request_projection_covers_all_five_tools(
    tool_name: str,
    arguments: Mapping[str, Any],
    expected_type: type[object],
) -> None:
    assert isinstance(_request_from_arguments(tool_name, arguments), expected_type)


def test_request_projection_preserves_bounded_arguments() -> None:
    system = _request_from_arguments(
        "system_inspect",
        {"sections": ["cpu", "memory"]},
    )
    assert isinstance(system, SystemInspectRequest)
    assert system.sections == (SystemSection.CPU, SystemSection.MEMORY)

    formats = _request_from_arguments(
        "probe_result_formats",
        {"include_warning": True, "nullable_value": "fixture", "array_length": 4},
    )
    assert formats == ProbeResultFormatsRequest(
        include_warning=True,
        nullable_value="fixture",
        array_length=4,
    )

    error = _request_from_arguments(
        "probe_error",
        {"case": "bounded_delay", "delay_ms": 10},
    )
    assert error == ProbeErrorRequest(case=ProbeErrorCase.BOUNDED_DELAY, delay_ms=10)


@pytest.mark.parametrize(
    ("tool_name", "arguments", "error_type"),
    [
        ("system_inspect", {"sections": "cpu"}, TypeError),
        ("system_inspect", {"sections": ["not-a-section"]}, ValueError),
        ("probe_error", {}, KeyError),
        ("probe_error", {"case": "not-a-case"}, ValueError),
        ("unknown", {}, ValueError),
    ],
)
def test_request_projection_rejects_invalid_values(
    tool_name: str,
    arguments: Mapping[str, Any],
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        _request_from_arguments(tool_name, arguments)


def test_handler_binding_loads_exact_async_callable() -> None:
    handler = _load_handler("binnacle.bootstrap.binnacle_probe.v1_1")

    assert callable(handler)


@pytest.mark.parametrize(
    ("structured", "fragment"),
    [
        (
            {
                "tool": {"name": "binnacle_probe"},
                "request_id": "req_fixture",
                "call_status": "succeeded",
                "data": {"build_version": "1.2.3", "device_id": "device_fixture"},
            },
            'build_version="1.2.3"',
        ),
        (
            {
                "tool": {"name": "probe_error"},
                "request_id": "req_fixture",
                "call_status": "execution_error",
                "error": {"code": "fixture", "message": "bounded failure"},
            },
            "execution error fixture: bounded failure",
        ),
        (
            {
                "tool": {"name": "probe_error"},
                "request_id": "req_fixture",
                "call_status": "execution_error",
                "error": "invalid",
            },
            "probe_error execution error",
        ),
        (
            {
                "call_status": "succeeded",
                "warnings": [{"code": "first"}, "invalid", {"code": "second"}],
            },
            "warnings=first,second",
        ),
    ],
)
def test_model_readable_text_is_bounded_and_consistent(
    structured: Mapping[str, Any],
    fragment: str,
) -> None:
    text = _model_readable_text(structured)

    assert fragment in text
    assert len(text) <= 4096


def test_model_readable_text_truncates_untrusted_fact() -> None:
    text = _model_readable_text(
        {
            "tool": {"name": "probe_result_formats"},
            "request_id": "req_fixture",
            "call_status": "succeeded",
            "data": {"string_value": "x" * 5000},
        }
    )

    assert len(text) == 4096


def test_model_readable_text_bound_is_utf8_bytes() -> None:
    text = _model_readable_text(
        {
            "tool": {"name": "probe_result_formats"},
            "request_id": "req_fixture",
            "call_status": "succeeded",
            "data": {"string_value": "é" * 5000},
        }
    )

    assert len(text.encode("utf-8")) <= 4096


def test_request_bound_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        RequestBodyLimitMiddleware(RecordingASGIApp(), max_request_bytes=0)


@pytest.mark.anyio
@pytest.mark.parametrize(("method", "path"), [("GET", "/readyz"), ("POST", "/readyz")])
async def test_non_target_requests_bypass_body_buffering(method: str, path: str) -> None:
    downstream, sent = await _exercise_middleware(method=method, path=path)

    assert downstream.calls == 1
    assert sent[0]["status"] == 200


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["GET", "DELETE"])
async def test_non_post_mcp_transport_requires_a_reviewed_revision(method: str) -> None:
    downstream, sent = await _exercise_middleware(
        method=method,
        headers=[(b"mcp-session-id", b"session-fixture")],
    )

    assert downstream.calls == 0
    assert sent[0]["status"] == 400
    assert _response_json(sent)["error"]["data"]["code"] == ("unsupported_protocol_version")


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["GET", "DELETE"])
async def test_non_post_legacy_transport_without_session_is_rejected(
    method: str,
) -> None:
    downstream, sent = await _exercise_middleware(
        method=method,
        headers=[
            (b"mcp-protocol-version", b"2025-11-25"),
        ],
    )

    assert downstream.calls == 0
    assert sent[0]["status"] == 400
    assert _response_json(sent)["error"]["message"] == (
        "The legacy transport request requires a bound Mcp-Session-Id."
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("headers", "status", "code"),
    [
        (
            [(b"content-length", b"1"), (b"Content-Length", b"1")],
            400,
            "invalid_content_length",
        ),
        ([(b"content-length", b"not-an-int")], 400, "invalid_content_length"),
        ([(b"content-length", b"-1")], 400, "invalid_content_length"),
        ([(b"content-length", b"65")], 413, "request_too_large"),
    ],
)
async def test_content_length_failures_are_rejected_before_downstream(
    headers: list[tuple[bytes, bytes]],
    status: int,
    code: str,
) -> None:
    downstream, sent = await _exercise_middleware(headers=headers)

    assert downstream.calls == 0
    assert sent[0]["status"] == status
    assert _response_json(sent) == {"error": code}


@pytest.mark.anyio
async def test_chunked_body_is_bounded_without_content_length() -> None:
    downstream, sent = await _exercise_middleware(
        max_request_bytes=3,
        messages=[
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"4", "more_body": False},
        ],
    )

    assert downstream.calls == 0
    assert sent[0]["status"] == 413
    assert _response_json(sent) == {"error": "request_too_large"}


@pytest.mark.anyio
async def test_unsupported_handshake_revision_is_rejected_before_body_parsing() -> None:
    downstream, sent = await _exercise_middleware(
        headers=[(b"mcp-protocol-version", b"2024-11-05")],
        messages=[{"type": "http.request", "body": b"{"}],
    )

    assert downstream.calls == 0
    assert sent[0]["status"] == 400
    assert _response_json(sent)["error"]["data"]["code"] == ("unsupported_protocol_version")


@pytest.mark.anyio
async def test_valid_chunked_body_is_coalesced_for_constant_message_replay() -> None:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "binnacle-test", "version": "1"},
            },
        }
    ).encode()
    midpoint = len(body) // 2
    downstream, sent = await _exercise_middleware(
        max_request_bytes=1024,
        headers=[(b"mcp-protocol-version", b"2025-11-25")],
        messages=[
            {"type": "http.request", "body": body[:midpoint], "more_body": True},
            {"type": "http.request", "body": body[midpoint:], "more_body": False},
        ],
    )

    assert downstream.calls == 1
    assert downstream.received == [{"type": "http.request", "body": body}]
    assert sent[0]["status"] == 200


@pytest.mark.anyio
async def test_empty_chunk_count_is_bounded() -> None:
    downstream, sent = await _exercise_middleware(
        messages=[{"type": "http.request", "body": b"", "more_body": True} for _ in range(1025)],
    )

    assert downstream.calls == 0
    assert sent[0]["status"] == 413
    assert _response_json(sent) == {"error": "request_too_large"}


@pytest.mark.anyio
async def test_invalid_json_is_replayed_to_framework_validation() -> None:
    downstream, sent = await _exercise_middleware(
        headers=[(b"mcp-protocol-version", b"2026-07-28")],
        messages=[{"type": "http.request", "body": b"{"}],
    )

    assert downstream.calls == 1
    assert downstream.received == [{"type": "http.request", "body": b"{"}]
    assert sent[0]["status"] == 200


@pytest.mark.anyio
async def test_json_integer_digit_limit_is_rejected_before_downstream() -> None:
    body = b'{"jsonrpc":"2.0","id":' + (b"9" * 5000) + b',"method":"tools/list"}'
    downstream, sent = await _exercise_middleware(
        max_request_bytes=8192,
        headers=[(b"mcp-protocol-version", b"2026-07-28")],
        messages=[{"type": "http.request", "body": body}],
    )

    assert len(body) < 8192
    assert downstream.calls == 0
    assert sent[0]["status"] == 400
    assert _response_json(sent) == {"error": "invalid_request_body"}


@pytest.mark.anyio
async def test_legacy_initialize_is_forwarded_without_binnacle_session_storage() -> None:
    downstream = RecordingASGIApp(
        response_headers=[(b"mcp-session-id", b"session-fixture")],
    )
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "binnacle-test", "version": "1"},
            },
        }
    ).encode()
    middleware = RequestBodyLimitMiddleware(downstream, max_request_bytes=1024)
    sent: list[ASGIMessage] = []
    queue: list[ASGIMessage] = [{"type": "http.request", "body": body}]

    async def receive() -> ASGIMessage:
        return queue.pop(0) if queue else {"type": "http.disconnect"}

    async def send(message: ASGIMessage) -> None:
        sent.append(message)

    await middleware(
        {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [(b"mcp-protocol-version", b"2025-11-25")],
        },
        receive,
        send,
    )

    assert downstream.calls == 1
    assert not hasattr(middleware, "_legacy_session_revisions")
    assert sent[0]["status"] == 200
    response_headers = dict(sent[0]["headers"])
    assert response_headers[b"mcp-session-id"] != b"session-fixture"
    assert response_headers[b"mcp-session-id"].startswith(b"b1.")


def test_revision_guard_accepts_only_configured_revisions() -> None:
    guard = RevisionGuardMiddleware(("2026-07-28",))

    guard._require_supported("2026-07-28")
    with pytest.raises(MCPError, match="Unsupported Binnacle MCP revision"):
        guard._require_supported("2024-11-05")
