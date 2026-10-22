"""P2.8 synthetic wire/client error paths; no provider process launched."""

from __future__ import annotations

import asyncio

import pytest

from binnacle.features.development_intelligence.lsp_client import (
    LspClient,
    LspProtocolError,
)
from tests.unit.core.test_lsp_client_wire import _peer


@pytest.mark.asyncio
async def test_constructor_refuses_invalid_deadlines_and_capacity():
    for kwargs, reason in (
        ({"request_timeout": 0}, "invalid_lsp_request_limits"),
        ({"max_pending": 0}, "invalid_lsp_request_limits"),
        ({"max_pending": 1025}, "invalid_lsp_request_limits"),
        ({"max_notifications": 0}, "invalid_lsp_notification_limit"),
        ({"max_notifications": 1025}, "invalid_lsp_notification_limit"),
    ):
        with pytest.raises(ValueError, match=reason):
            LspClient(asyncio.StreamReader(), object(), **kwargs)


@pytest.mark.asyncio
async def test_client_start_after_close_and_idempotent_close():
    reader, writer, client = _peer()
    await client.aclose()
    await client.aclose()
    with pytest.raises(LspProtocolError, match="lsp_client_closed"):
        client.start()
    assert writer.sent == []
    assert not reader.at_eof()


@pytest.mark.asyncio
async def test_rejects_invalid_query_and_notify_method_without_writing():
    _reader, writer, client = _peer()
    try:
        with pytest.raises(ValueError, match="invalid_lsp_method"):
            await client.request(0)
        with pytest.raises(ValueError, match="invalid_lsp_method"):
            await client.request("")
        with pytest.raises(ValueError, match="invalid_lsp_method"):
            await client.notify("")
        for deadline in (0, -1, 121):
            with pytest.raises(ValueError, match="invalid_lsp_deadline"):
                await client.request("valid-name", timeout=deadline)
        client._next_id = 2**31
        with pytest.raises(LspProtocolError, match="request_id_exhausted"):
            await client.request("valid-name")
        assert writer.sent == []
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_request_and_notify_before_start_fail_cleanly():
    reader = asyncio.StreamReader()
    client = LspClient(reader, object())
    with pytest.raises(LspProtocolError, match="lsp_client_not_started"):
        await client.request("not-yet")
    with pytest.raises(LspProtocolError, match="lsp_client_not_started"):
        await client.notify("not-yet")
    await client.aclose()


@pytest.mark.asyncio
async def test_close_cancels_outstanding_remote_cancel_tasks():
    _reader, _writer, client = _peer()
    entered = asyncio.Event()

    async def cancellation_sender():
        entered.set()
        await asyncio.Event().wait()

    background = asyncio.create_task(cancellation_sender())
    client._cancel_tasks.add(background)
    await asyncio.wait_for(entered.wait(), 1)
    await asyncio.wait_for(client.aclose(), 1)
    assert background.cancelled()
    assert client._closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,reason",
    [
        ({"jsonrpc": "1.0", "method": "fake/notify"}, "invalid_json_rpc_version"),
        ({"jsonrpc": "2.0", "method": 1}, "invalid_json_rpc_method"),
        (
            {"jsonrpc": "2.0", "method": "fake/x", "result": 1},
            "malformed_json_rpc_method",
        ),
        (
            {"jsonrpc": "2.0", "id": 1, "result": 1, "error": {}},
            "invalid_json_rpc_response",
        ),
    ],
)
async def test_receive_dispatch_rejects_malformed_responses(payload, reason):
    _reader, _writer, client = _peer()
    try:
        with pytest.raises(LspProtocolError, match=reason):
            await client._dispatch(payload)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_nonprotocol_reader_failure_is_sanitized():
    reader, _writer, client = _peer()
    reader.set_exception(RuntimeError("a path that must not be returned"))
    for _ in range(20):
        if client.failure_reason is not None:
            break
        await asyncio.sleep(0)
    assert client.failure_reason == "lsp_read_failed"
    await client.aclose()
