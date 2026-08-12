"""Bounded one-request-per-connection UDS client with mutual peer authentication."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, TypeVar

from binnacle.domain.execution import (
    ExecutionStartReceipt,
    ExecutionTicket,
    ExecutorCancelReceipt,
    ExecutorHello,
    ExecutorOutputChunk,
    ExecutorSnapshot,
    NoAcceptSealResult,
    OutputStream,
    TicketRoutingIdentity,
    canonical_timestamp,
)
from binnacle.executor.protocol import (
    ExecutorProtocolError,
    cancel_receipt_from_wire,
    no_accept_result_from_wire,
    output_chunk_from_wire,
    read_frame,
    request_envelope,
    require_peer,
    routing_identity_to_wire,
    snapshot_from_wire,
    start_receipt_from_wire,
    validate_response,
    write_frame,
)

_MAX_LIST_ITEMS: Final = 256
_Decoded = TypeVar("_Decoded")


class ExecutorClientError(RuntimeError):
    """The local executor is unavailable, incompatible, or returned invalid evidence."""


@dataclass(frozen=True, slots=True)
class ExecutorClientSettings:
    socket_path: Path = Path("/run/binnacle-executor/supervisor.sock")
    expected_peer_uid: int = -1
    expected_peer_gid: int = -1
    connect_timeout_seconds: float = 2.0
    request_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if min(self.expected_peer_uid, self.expected_peer_gid) < 0:
            raise ExecutorClientError("executor peer identity is not configured")
        if not 0.1 <= self.connect_timeout_seconds <= 10:
            raise ExecutorClientError("executor connect timeout is outside the safe range")
        if not 0.1 <= self.request_timeout_seconds <= 60:
            raise ExecutorClientError("executor request timeout is outside the safe range")
        if not self.socket_path.is_absolute():
            raise ExecutorClientError("executor socket path must be absolute")


class ExecutorClient:
    def __init__(self, settings: ExecutorClientSettings) -> None:
        self._settings = settings

    async def hello(self) -> ExecutorHello:
        value = await self._exchange("hello")
        raw = _exact_result(
            value,
            {
                "protocol_id",
                "protocol_version",
                "build_sha256",
                "profile_sha256",
                "supervisor_instance_id",
                "supervisor_generation",
                "backend_ready",
                "readiness",
            },
        )
        return _decode_result(
            lambda: ExecutorHello(
                protocol_id=_text(raw, "protocol_id"),
                protocol_version=_text(raw, "protocol_version"),
                build_sha256=_text(raw, "build_sha256"),
                profile_sha256=_text(raw, "profile_sha256"),
                supervisor_instance_id=_text(raw, "supervisor_instance_id"),
                supervisor_generation=_integer(raw, "supervisor_generation"),
                backend_ready=_boolean(raw, "backend_ready"),
                readiness=_text(raw, "readiness"),
            )
        )

    async def start(self, ticket: ExecutionTicket) -> ExecutionStartReceipt:
        value = await self._exchange("start_execution", ticket=ticket.to_wire())
        return _decode_result(lambda: start_receipt_from_wire(value))

    async def get(self, operation_id: str) -> ExecutorSnapshot | None:
        value = await self._exchange("get_execution", operation_id=operation_id)
        return None if value is None else _decode_result(lambda: snapshot_from_wire(value))

    async def read_output(
        self,
        operation_id: str,
        stream: OutputStream,
        offset: int,
        max_bytes: int,
    ) -> ExecutorOutputChunk:
        value = await self._exchange(
            "read_output",
            operation_id=operation_id,
            stream=stream.value,
            offset=offset,
            max_bytes=max_bytes,
        )
        return _decode_result(lambda: output_chunk_from_wire(value))

    async def cancel(
        self,
        identity: TicketRoutingIdentity,
        cancel_generation: int,
        execution_id: str | None = None,
    ) -> ExecutorCancelReceipt:
        value = await self._exchange(
            "request_cancel",
            identity=routing_identity_to_wire(identity),
            cancel_generation=cancel_generation,
            execution_id=execution_id,
        )
        return _decode_result(lambda: cancel_receipt_from_wire(value))

    async def seal_no_accept(
        self,
        identity: TicketRoutingIdentity,
        reason: str,
        close_generation: int,
        retain_until: datetime,
    ) -> NoAcceptSealResult:
        value = await self._exchange(
            "seal_no_accept",
            identity=routing_identity_to_wire(identity),
            reason=reason,
            close_generation=close_generation,
            retain_until=canonical_timestamp(retain_until),
        )
        return _decode_result(lambda: no_accept_result_from_wire(value))

    async def list(self, operation_ids: tuple[str, ...]) -> tuple[ExecutorSnapshot, ...]:
        if len(operation_ids) > _MAX_LIST_ITEMS:
            raise ExecutorClientError("executor list request exceeds the reviewed limit")
        value = await self._exchange("list_executions", operation_ids=list(operation_ids))
        if not isinstance(value, list):
            raise ExecutorClientError("executor list response is invalid")
        return _decode_result(lambda: tuple(snapshot_from_wire(item) for item in value))

    async def _exchange(self, message_type: str, **fields: object) -> object:
        request_id = f"req_{secrets.token_hex(16)}"
        request = request_envelope(request_id, message_type, **fields)
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self._settings.socket_path),
                timeout=self._settings.connect_timeout_seconds,
            )
            try:
                peer_socket = writer.get_extra_info("socket")
                if peer_socket is None:
                    raise ExecutorClientError("executor connection has no peer socket")
                require_peer(
                    peer_socket,
                    expected_uid=self._settings.expected_peer_uid,
                    expected_gid=self._settings.expected_peer_gid,
                )
                await asyncio.wait_for(
                    write_frame(writer, request),
                    timeout=self._settings.request_timeout_seconds,
                )
                response = await asyncio.wait_for(
                    read_frame(reader),
                    timeout=self._settings.request_timeout_seconds,
                )
                validate_response(response, request_id=request_id)
            finally:
                writer.close()
                await writer.wait_closed()
        except (OSError, TimeoutError, ExecutorProtocolError) as exc:
            raise ExecutorClientError("executor request failed closed") from exc
        if response["type"] != f"{message_type}_result":
            raise ExecutorClientError("executor response type is invalid")
        if not response["ok"]:
            error = response["error"]
            if not isinstance(error, dict) or set(error) != {"code"}:
                raise ExecutorClientError("executor error response is invalid")
            code = error.get("code")
            if not isinstance(code, str):
                raise ExecutorClientError("executor error code is invalid")
            raise ExecutorClientError(f"executor rejected request: {code}")
        return response["result"]


def _exact_result(value: object, fields: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ExecutorClientError("executor result fields are invalid")
    return value


def _decode_result(factory: Callable[[], _Decoded]) -> _Decoded:
    try:
        return factory()
    except (ExecutorProtocolError, ValueError) as exc:
        raise ExecutorClientError("executor returned invalid evidence") from exc


def _text(value: dict[str, object], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str):
        raise ExecutorClientError(f"executor {name} is invalid")
    return result


def _integer(value: dict[str, object], name: str) -> int:
    result = value.get(name)
    if isinstance(result, bool) or not isinstance(result, int):
        raise ExecutorClientError(f"executor {name} is invalid")
    return result


def _boolean(value: dict[str, object], name: str) -> bool:
    result = value.get(name)
    if not isinstance(result, bool):
        raise ExecutorClientError(f"executor {name} is invalid")
    return result


__all__ = ["ExecutorClient", "ExecutorClientError", "ExecutorClientSettings"]
