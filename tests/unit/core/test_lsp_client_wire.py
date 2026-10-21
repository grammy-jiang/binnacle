"""P2.2 production bounded frame parser and async RPC routing, synthetic only."""

import asyncio
from collections.abc import Callable

import pytest

from binnacle.features.development_intelligence.lsp_client import (
    LspClient,
    LspProtocolError,
    LspRemoteError,
)
from binnacle.features.development_intelligence.lsp_wire import (
    LspFrameDecoder,
    encode_frame,
)


class MemoryWriter:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        *,
        on_send: Callable[[dict], None] | None = None,
    ) -> None:
        self.reader = reader
        self.sent: list[dict] = []
        self.parser = LspFrameDecoder()
        self.on_send = on_send
        self.fail_drain = False

    def write(self, data: bytes) -> None:
        for message in self.parser.feed(data):
            self.sent.append(message)
            if self.on_send is not None:
                self.on_send(message)

    async def drain(self) -> None:
        if self.fail_drain:
            raise BrokenPipeError
        await asyncio.sleep(0)

    def server(self, message: dict) -> None:
        self.reader.feed_data(encode_frame(message))


def _peer(on_send=None, **options):
    reader = asyncio.StreamReader()
    writer = MemoryWriter(reader, on_send=on_send)
    client = LspClient(reader, writer, **options)
    client.start()
    return reader, writer, client


@pytest.mark.parametrize(
    "mode",
    [
        "split",
        "coalesced",
    ],
)
def test_incremental_utf8_frame_stream(mode):
    a = {"jsonrpc": "2.0", "id": 1, "result": "文 🧭"}
    b = {"jsonrpc": "2.0", "method": "fixture/tick", "params": {}}
    data = encode_frame(a) + encode_frame(b)
    decoder = LspFrameDecoder()
    if mode == "split":
        got = [msg for byte in data for msg in decoder.feed(bytes([byte]))]
    else:
        got = decoder.feed(data)
    decoder.finish()
    assert got == [a, b]
    assert decoder.buffered_bytes == 0


@pytest.mark.parametrize(
    ("wire", "reason"),
    [
        (b"Content-Type: test\r\n\r\n{}", "missing_or_duplicate_content_length"),
        (b"Content-Length: nope\r\n\r\n{}", "invalid_content_length"),
        (b"Content-Length: -1\r\n\r\n{}", "invalid_content_length"),
        (b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}", "missing_or_duplicate"),
        (b"Content-Length: 9\r\n\r\n{}", "truncated_frame"),
        (b"Content-Length: 2\r\n\r\n[]", "json_rpc_not_object"),
        (b"Content-Length: 1\r\n\r\n{", "invalid_json_body"),
        (b'Content-Length: 13\r\n\r\n{"x":1,"x":2}', "duplicate_json_field"),
        (b'Content-Length: 9\r\n\r\n{"x":NaN}', "invalid_json_constant"),
    ],
)
def test_bad_frame_refusal(wire, reason):
    decoder = LspFrameDecoder()
    with pytest.raises(LspProtocolError, match=reason):
        decoder.feed(wire)
        decoder.finish()


def test_header_and_body_limits_reject_excessive_data():
    with pytest.raises(LspProtocolError, match="header_too_large"):
        LspFrameDecoder(max_header=64).feed(b"X-Header: " + b"x" * 100)
    with pytest.raises(LspProtocolError, match="body_too_large"):
        LspFrameDecoder(max_body=16).feed(b"Content-Length: 17\r\n\r\n")
    with pytest.raises(LspProtocolError, match="outbound_body_too_large"):
        encode_frame({"secret": "x" * 100}, max_body=8)


def test_outbound_nan_is_rejected():
    with pytest.raises(LspProtocolError, match="invalid_outbound_json"):
        encode_frame({"bad": float("nan")})


def test_concurrent_out_of_order_id_response_routing():
    async def exercise():
        _, writer, client = _peer()
        try:
            first = asyncio.create_task(client.request("a", {"n": 1}))
            second = asyncio.create_task(client.request("b", {"n": 2}))
            for _ in range(8):
                if len(writer.sent) == 2:
                    break
                await asyncio.sleep(0)
            assert len(writer.sent) == 2
            assert {item["id"] for item in writer.sent} == {1, 2}
            writer.server({"jsonrpc": "2.0", "id": 2, "result": "second"})
            writer.server({"jsonrpc": "2.0", "id": 1, "result": "first"})
            assert await asyncio.gather(first, second) == ["first", "second"]
            assert client.pending_count == 0
        finally:
            await client.aclose()

    asyncio.run(exercise())


def test_remote_errors_are_sanitized_and_not_raw():
    async def exercise():
        def response(request):
            writer.server(
                {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "error": {"code": -32000, "message": "do-not-echo-secret"},
                }
            )

        _, writer, client = _peer(on_send=response)
        try:
            with pytest.raises(LspRemoteError) as raised:
                await client.request("bad")
            assert raised.value.code == -32000
            assert "do-not-echo-secret" not in str(raised.value)
        finally:
            await client.aclose()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("id_value", "expected"),
    [
        (True, "unexpected_response_id"),
        (None, "unexpected_response_id"),
        ([1], "unexpected_response_id"),
        (989, "unmatched_response_id"),
    ],
)
def test_invalid_and_unmatched_response_ids_fail_closed(id_value, expected):
    async def exercise():
        _, writer, client = _peer()
        try:
            operation = asyncio.create_task(client.request("fixture/await"))
            await asyncio.sleep(0)
            writer.server({"jsonrpc": "2.0", "id": id_value, "result": None})
            with pytest.raises(LspProtocolError, match=expected):
                await operation
            assert client.pending_count == 0
        finally:
            await client.aclose()

    asyncio.run(exercise())


def test_duplicate_fulfilled_response_is_protocol_failure():
    async def exercise():
        _, writer, client = _peer()
        try:
            operation = asyncio.create_task(client.request("fixture/await"))
            await asyncio.sleep(0)
            answer = {"jsonrpc": "2.0", "id": 1, "result": 42}
            writer.reader.feed_data(encode_frame(answer) + encode_frame(answer))
            # Depending on reader/write scheduling, a corrupt duplicate
            # response can fail before or just after delivering the first
            # result. It must ALWAYS poison the protocol connection.
            try:
                assert await operation == 42
            except LspProtocolError:
                pass
            assert client.failure_reason in (
                "duplicate_response_id",
                "unmatched_response_id",
            )
        finally:
            await client.aclose()

    asyncio.run(exercise())


def test_deadline_and_late_reply_never_match_next_request():
    async def exercise():
        _, writer, client = _peer(request_timeout=0.05)
        try:
            with pytest.raises(asyncio.TimeoutError):
                await client.request("fixture/hang")
            for _ in range(32):
                if writer.sent[-1]["method"] == "$/cancelRequest":
                    break
                await asyncio.sleep(0)
            assert writer.sent[-1]["method"] == "$/cancelRequest"
            writer.server({"jsonrpc": "2.0", "id": 1, "result": "late"})
            follow = asyncio.create_task(client.request("fixture/next"))
            await asyncio.sleep(0)
            writer.server({"jsonrpc": "2.0", "id": 2, "result": "new"})
            assert await follow == "new"
            assert client.pending_count == 0
            assert client.failure_reason is None
        finally:
            await client.aclose()

    asyncio.run(exercise())


def test_canceled_request_has_remote_cancel_notification():
    async def exercise():
        _, writer, client = _peer()
        try:
            task = asyncio.create_task(client.request("fixture/hang"))
            # Cancellation after confirmed write/delivery: the nested write
            # timeout and request task each need event loop dispatch turns.
            for _ in range(12):
                await asyncio.sleep(0)
            assert writer.sent[0]["method"] == "fixture/hang"
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            for _ in range(12):
                if writer.sent[-1]["method"] == "$/cancelRequest":
                    break
                await asyncio.sleep(0)
            assert writer.sent[-1] == {
                "jsonrpc": "2.0",
                "method": "$/cancelRequest",
                "params": {"id": 1},
            }
            assert client.pending_count == 0
        finally:
            await client.aclose()

    asyncio.run(exercise())


def test_server_notifications_remain_separate_and_bounded():
    async def exercise():
        _, writer, client = _peer(max_notifications=1)
        try:
            writer.server(
                {
                    "jsonrpc": "2.0",
                    "method": "window/logMessage",
                    "params": {"message": "local-only"},
                }
            )
            item = await client.next_notification()
            assert item["method"] == "window/logMessage"
            writer.server({"jsonrpc": "2.0", "method": "one"})
            writer.server({"jsonrpc": "2.0", "method": "two"})
            await asyncio.sleep(0)
            assert client.failure_reason == "notification_queue_full"
        finally:
            await client.aclose()

    asyncio.run(exercise())


def test_missing_peer_and_writer_failure_both_fail_outstanding():
    async def exercise():
        reader, writer, client = _peer()
        try:
            operation = asyncio.create_task(client.request("fixture/pending"))
            await asyncio.sleep(0)
            reader.feed_eof()
            with pytest.raises(LspProtocolError, match="lsp_peer_eof"):
                await operation
        finally:
            await client.aclose()

        _, writer, client = _peer()
        writer.fail_drain = True
        try:
            with pytest.raises(LspProtocolError, match="lsp_write_failed"):
                await client.request("fixture/bad")
        finally:
            await client.aclose()

    asyncio.run(exercise())


def test_pending_limit_requires_resolution():
    async def exercise():
        _, _, client = _peer(max_pending=1)
        try:
            pending = asyncio.create_task(client.request("fixture/pending"))
            await asyncio.sleep(0)
            with pytest.raises(LspProtocolError, match="pending_request_limit"):
                await client.request("fixture/other")
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        finally:
            await client.aclose()

    asyncio.run(exercise())


def test_finite_json_number_required():
    from binnacle.features.development_intelligence.lsp_wire import decode_json

    assert decode_json(b'{"value":1.25}') == {"value": 1.25}
    with pytest.raises(LspProtocolError, match="invalid_json_number"):
        decode_json(b'{"value":1e309}')


def test_bounded_decoder_refuses_single_oversized_input_fragment():
    with pytest.raises(LspProtocolError, match="frame_fragment_too_large"):
        LspFrameDecoder(max_header=64, max_body=16).feed(b"x" * 100)


def test_invalid_remote_error_response_cannot_be_treated_as_success():
    async def exercise():
        _, writer, client = _peer()
        try:
            waiting = asyncio.create_task(client.request("pending"))
            await asyncio.sleep(0)
            writer.server(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"code": -32601, "message": False},
                }
            )
            with pytest.raises(LspProtocolError, match="invalid_json_rpc_error"):
                await waiting
            assert client.pending_count == 0
        finally:
            await client.aclose()

    asyncio.run(exercise())


def test_lsp_client_does_not_own_or_close_injected_pipes():
    async def exercise():
        reader, writer, client = _peer()
        await client.aclose()
        assert not reader.at_eof()
        writer.server({"jsonrpc": "2.0", "method": "still-writable"})
        assert not reader.at_eof()
        with pytest.raises(LspProtocolError, match="lsp_client_closed"):
            await client.request("after-close")

    asyncio.run(exercise())


def test_outgoing_deadline_covers_a_stalled_writer_drain():
    async def exercise():
        reader = asyncio.StreamReader()
        blocked = asyncio.Event()

        class StalledWriter:
            def write(self, _data: bytes) -> None:
                pass

            async def drain(self) -> None:
                await blocked.wait()

        client = LspClient(reader, StalledWriter(), request_timeout=0.02)
        client.start()
        try:
            with pytest.raises((asyncio.TimeoutError, LspProtocolError)):
                await asyncio.wait_for(client.request("fixture/stalled"), timeout=0.4)
            assert client.pending_count == 0
            assert client.failure_reason in (
                "lsp_write_timeout",
                "lsp_write_interrupted",
            )
            with pytest.raises(LspProtocolError):
                await client.request("fixture/no-reuse")
        finally:
            await client.aclose()

    asyncio.run(exercise())


def test_reverse_notification_writer_backpressure_is_also_bounded():
    async def exercise():
        reader = asyncio.StreamReader()

        class StalledWriter:
            def write(self, _data: bytes) -> None:
                pass

            async def drain(self) -> None:
                await asyncio.Event().wait()

        client = LspClient(reader, StalledWriter(), request_timeout=0.02)
        client.start()
        try:
            with pytest.raises(LspProtocolError, match="lsp_write_timeout"):
                await asyncio.wait_for(client.notify("initialized", {}), 0.4)
            assert client.failure_reason == "lsp_write_timeout"
        finally:
            await client.aclose()

    asyncio.run(exercise())


def test_writer_exception_never_leaks_unretrieved_future_error():
    async def exercise():
        loop = asyncio.get_running_loop()
        observed = []
        previous = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, ctx: observed.append(ctx))
        _, writer, client = _peer()
        writer.fail_drain = True
        try:
            with pytest.raises(LspProtocolError, match="lsp_write_failed"):
                await client.request("fixture/writer-error")
            assert client.pending_count == 0
            await asyncio.sleep(0)
        finally:
            await client.aclose()
            loop.set_exception_handler(previous)
        assert not observed, [
            str(item.get("message", "unhandled")) for item in observed
        ]

    asyncio.run(exercise())
