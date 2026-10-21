"""Small async JSON-RPC 2.0 LSP peer over injected stdio reader/writer.

P2.2/2.3 protocol only: the P2.4 owner supplies transports and is separately
responsible for process lifetime, SIGTERM/SIGKILL and descendant cleanup.
No raw request/response content or child stderr is logged here.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Mapping
from typing import Any, Protocol

from .lsp_policy import server_request_reply
from .lsp_wire import LspFrameDecoder, LspProtocolError, encode_frame


class LspWriter(Protocol):
    def write(self, data: bytes) -> None: ...

    async def drain(self) -> None: ...


class LspRemoteError(Exception):
    """Sanitized remote JSON-RPC error; original server message is untrusted."""

    def __init__(self, code: int):
        self.code = code
        super().__init__("remote_rpc_error")


class LspClient:
    """Concurrent request routing with strict ID checks and safe reverse RPCs."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: LspWriter,
        *,
        request_timeout: float = 3.0,
        max_body: int = 1024 * 1024,
        max_pending: int = 128,
        max_notifications: int = 64,
        configuration: Mapping[str, dict] | None = None,
    ) -> None:
        if not (0 < request_timeout <= 120 and 1 <= max_pending <= 1024):
            raise ValueError("invalid_lsp_request_limits")
        if not 1 <= max_notifications <= 1024:
            raise ValueError("invalid_lsp_notification_limit")
        self._reader = reader
        self._writer = writer
        self._decoder = LspFrameDecoder(max_body=max_body)
        self._request_timeout = request_timeout
        self._max_body = max_body
        self._max_pending = max_pending
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._retired: deque[int] = deque(maxlen=512)
        self._notifications: asyncio.Queue[dict] = asyncio.Queue(max_notifications)
        self._configuration = configuration
        self._write_lock = asyncio.Lock()
        self._reader_task: asyncio.Task[None] | None = None
        self._cancel_tasks: set[asyncio.Task[None]] = set()
        self._next_id = 1
        self._fatal: LspProtocolError | None = None
        self._closed = False

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def failure_reason(self) -> str | None:
        return str(self._fatal) if self._fatal is not None else None

    def start(self) -> None:
        if self._closed:
            raise LspProtocolError("lsp_client_closed")
        if self._reader_task is None:
            self._reader_task = asyncio.create_task(self._receive_loop())

    async def request(
        self, method: str, params: dict | None = None, *, timeout: float | None = None
    ) -> Any:
        self._ensure_running()
        if not isinstance(method, str) or not method:
            raise ValueError("invalid_lsp_method")
        if len(self._pending) >= self._max_pending:
            raise LspProtocolError("pending_request_limit")
        if self._next_id > 2**31 - 1:
            raise LspProtocolError("request_id_exhausted")
        deadline = self._request_timeout if timeout is None else timeout
        if not 0 < deadline <= 120:
            raise ValueError("invalid_lsp_deadline")
        request_id = self._next_id
        self._next_id += 1
        pending = asyncio.get_running_loop().create_future()
        self._pending[request_id] = pending
        sent = False

        async def exchange() -> Any:
            nonlocal sent
            await self._send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": {} if params is None else params,
                }
            )
            sent = True
            return await asyncio.shield(pending)

        try:
            # One deadline covers write-lock acquisition, drain and response.
            # A stalled transport must never strand an outstanding RPC.
            return await asyncio.wait_for(exchange(), deadline)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._retire(request_id)
            if not sent:
                # Sending may have been partially completed; do not reuse an
                # indeterminate stdio stream or assume a remote cancel arrived.
                self._fail(LspProtocolError("lsp_write_interrupted"))
            else:
                task = asyncio.create_task(self._cancel_remote(request_id))
                self._cancel_tasks.add(task)
                task.add_done_callback(self._cancel_tasks.discard)
            raise
        finally:
            self._pending.pop(request_id, None)
            if not pending.done():
                pending.cancel()
            elif not pending.cancelled():
                # A transport write can fail after _fail() populated the
                # Future, before request() ever awaited its result. Observe
                # that exception to avoid an unhandled Future error warning.
                pending.exception()

    async def notify(self, method: str, params: dict | None = None) -> None:
        self._ensure_running()
        if not isinstance(method, str) or not method:
            raise ValueError("invalid_lsp_method")
        await self._send(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": {} if params is None else params,
            }
        )

    async def next_notification(self, *, timeout: float = 3.0) -> dict:
        self._ensure_running()
        return await asyncio.wait_for(self._notifications.get(), timeout)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._fail(LspProtocolError("lsp_client_closed"))
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        for task in list(self._cancel_tasks):
            task.cancel()
        if self._cancel_tasks:
            await asyncio.gather(*self._cancel_tasks, return_exceptions=True)
        # Injected stdio handles belong to P2.4. Do not close/kill them here.

    def _ensure_running(self) -> None:
        if self._fatal is not None:
            raise LspProtocolError(str(self._fatal))
        if self._closed:
            raise LspProtocolError("lsp_client_closed")
        if self._reader_task is None:
            raise LspProtocolError("lsp_client_not_started")

    async def _send(self, message: dict) -> None:
        data = encode_frame(message, max_body=self._max_body)

        async def write_one_frame() -> None:
            async with self._write_lock:
                self._ensure_running()
                self._writer.write(data)
                await self._writer.drain()

        try:
            # Bound reverse-request responses and notifications too, not just
            # requests. Never hold the writer lock forever under backpressure.
            await asyncio.wait_for(write_one_frame(), self._request_timeout)
        except asyncio.TimeoutError as exc:
            self._fail(LspProtocolError("lsp_write_timeout"))
            raise LspProtocolError("lsp_write_timeout") from exc
        except (OSError, ConnectionError, EOFError) as exc:
            self._fail(LspProtocolError("lsp_write_failed"))
            raise LspProtocolError("lsp_write_failed") from exc

    async def _cancel_remote(self, identifier: int) -> None:
        if not self._closed and self._fatal is None:
            try:
                await self.notify("$/cancelRequest", {"id": identifier})
            except (OSError, ValueError, asyncio.CancelledError):
                pass

    def _retire(self, identifier: int) -> None:
        self._pending.pop(identifier, None)
        self._retired.append(identifier)

    def _fail(self, error: LspProtocolError) -> None:
        if self._fatal is None:
            self._fatal = error
        for future in self._pending.values():
            if not future.done():
                future.set_exception(self._fatal)

    async def _receive_loop(self) -> None:
        try:
            while not self._closed:
                chunk = await self._reader.read(4096)
                if not chunk:
                    self._decoder.finish()
                    raise LspProtocolError("lsp_peer_eof")
                for message in self._decoder.feed(chunk):
                    await self._dispatch(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - reader boundary fails closed
            if isinstance(exc, LspProtocolError):
                error = exc
            else:
                error = LspProtocolError("lsp_read_failed")
            self._fail(error)

    async def _dispatch(self, message: dict) -> None:
        if message.get("jsonrpc") != "2.0":
            raise LspProtocolError("invalid_json_rpc_version")
        if "method" in message:
            method = message["method"]
            if not isinstance(method, str) or not method:
                raise LspProtocolError("invalid_json_rpc_method")
            if "result" in message or "error" in message:
                raise LspProtocolError("malformed_json_rpc_method")
            if "id" in message:
                await self._send(
                    server_request_reply(message, configuration=self._configuration)
                )
            else:
                if self._notifications.full():
                    raise LspProtocolError("notification_queue_full")
                self._notifications.put_nowait(message)
            return
        identifier = message.get("id")
        if type(identifier) is not int:
            raise LspProtocolError("unexpected_response_id")
        if ("result" in message) == ("error" in message):
            raise LspProtocolError("invalid_json_rpc_response")
        pending = self._pending.get(identifier)
        if pending is None:
            if identifier in self._retired:
                return  # Late reply to timed-out or canceled request.
            raise LspProtocolError("unmatched_response_id")
        if pending.done():
            raise LspProtocolError("duplicate_response_id")
        if "error" in message:
            error = message["error"]
            if (
                not isinstance(error, dict)
                or type(error.get("code")) is not int
                or not isinstance(error.get("message"), str)
            ):
                raise LspProtocolError("invalid_json_rpc_error")
            pending.set_exception(LspRemoteError(error["code"]))
        else:
            pending.set_result(message["result"])
