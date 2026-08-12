"""Concurrent, peer-authenticated executor protocol server.

The production composition deliberately has no start handler until a candidate-Pi backend
is promoted.  Control and reconciliation requests remain independently dispatchable.
"""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from binnacle.domain.execution import (
    EXECUTOR_PROTOCOL_ID,
    EXECUTOR_PROTOCOL_VERSION,
    MAX_OUTPUT_CHUNK_BYTES,
    CancelDisposition,
    CancelRoutingDisposition,
    ExecutionConflictError,
    ExecutionError,
    ExecutionStartReceipt,
    ExecutionTicket,
    ExecutorCancelReceipt,
    ExecutorOutputChunk,
    ExecutorSnapshot,
    OutputStream,
    canonical_sha256,
    validate_identifier,
)
from binnacle.executor.protocol import (
    ExecutorProtocolError,
    cancel_receipt_to_wire,
    error_response,
    no_accept_result_to_wire,
    output_chunk_to_wire,
    read_frame,
    require_peer,
    routing_identity_from_wire,
    snapshot_to_wire,
    start_receipt_to_wire,
    success_response,
    validate_request,
    write_frame,
)
from binnacle.executor.state import ExecutorStoreError
from binnacle.executor.tickets import ExecutionTicketRejected
from binnacle.ports.execution import ExecutorEvidenceStore

_READ_TIMEOUT_SECONDS: Final = 5.0
_WRITE_TIMEOUT_SECONDS: Final = 10.0
StartHandler = Callable[[ExecutionTicket], Awaitable[ExecutionStartReceipt]]
TicketValidator = Callable[[ExecutionTicket], object]
OutputReader = Callable[[str, OutputStream, int, int], Awaitable[ExecutorOutputChunk]]
ProtocolResult = Mapping[str, object] | list[object] | None


class ExecutorServerError(RuntimeError):
    """The inherited executor listener or service composition is unsafe."""


@dataclass(frozen=True, slots=True)
class ExecutorServerIdentity:
    build_sha256: str
    profile_sha256: str
    supervisor_instance_id: str
    supervisor_generation: int
    expected_client_uid: int
    expected_client_gid: int
    readiness: str = "recovering"

    def __post_init__(self) -> None:
        if (
            min(
                self.supervisor_generation,
                self.expected_client_uid,
                self.expected_client_gid,
            )
            < 0
            or self.supervisor_generation < 1
        ):
            raise ExecutorServerError("executor server identity is invalid")
        if self.readiness not in {"recovering", "ready", "integrity_failed"}:
            raise ExecutorServerError("executor readiness identity is invalid")


class ExecutionSupervisorService:
    def __init__(
        self,
        *,
        store: ExecutorEvidenceStore,
        identity: ExecutorServerIdentity,
        start_handler: StartHandler | None = None,
        ticket_validator: TicketValidator | None = None,
        output_reader: OutputReader | None = None,
    ) -> None:
        if (start_handler is None) != (ticket_validator is None):
            raise ExecutorServerError(
                "executor start handler and ticket validator must be promoted together"
            )
        self._store = store
        self._identity = identity
        self._start_handler = start_handler
        self._ticket_validator = ticket_validator
        self._output_reader = output_reader

    async def dispatch(self, request: dict[str, object]) -> ProtocolResult:
        message_type = _text(request, "type")
        if message_type == "hello":
            return {
                "protocol_id": EXECUTOR_PROTOCOL_ID,
                "protocol_version": EXECUTOR_PROTOCOL_VERSION,
                "build_sha256": self._identity.build_sha256,
                "profile_sha256": self._identity.profile_sha256,
                "supervisor_instance_id": self._identity.supervisor_instance_id,
                "supervisor_generation": self._identity.supervisor_generation,
                "backend_ready": self._start_handler is not None,
                "readiness": self._identity.readiness,
            }
        if message_type == "start_execution":
            if self._start_handler is None or self._ticket_validator is None:
                raise ExecutionTicketRejected("execution backend is not promoted")
            ticket_value = request["ticket"]
            if not isinstance(ticket_value, dict):
                raise ExecutorProtocolError("execution ticket must be one object")
            ticket = ExecutionTicket.from_wire(ticket_value)
            self._ticket_validator(ticket)
            return start_receipt_to_wire(await self._start_handler(ticket))
        if message_type == "get_execution":
            operation_id = _operation_id(request)
            snapshot = await self._store.get(operation_id)
            return None if snapshot is None else snapshot_to_wire(snapshot)
        if message_type == "list_executions":
            values = request["operation_ids"]
            if (
                not isinstance(values, list)
                or len(values) > 256
                or not all(isinstance(value, str) for value in values)
            ):
                raise ExecutorProtocolError("executor operation list is invalid")
            operation_ids = tuple(values)
            for operation_id in operation_ids:
                validate_identifier(operation_id, name="operation_id")
            return [snapshot_to_wire(item) for item in await self._store.list(operation_ids)]
        if message_type == "request_cancel":
            identity = routing_identity_from_wire(request["identity"])
            generation = _integer(request, "cancel_generation")
            expected_execution_id = _optional_text(request, "execution_id")
            routed = await self._store.cancel_or_attach(
                identity=identity,
                cancel_generation=generation,
            )
            if (
                expected_execution_id is not None
                and routed.snapshot is not None
                and routed.snapshot.execution_id != expected_execution_id
            ):
                raise ExecutionConflictError("cancel execution identity is stale")
            disposition = _cancel_disposition(routed.disposition, routed.snapshot)
            receipt_sha256 = canonical_sha256(
                {
                    "acknowledged_cancel_generation": routed.acknowledged_cancel_generation,
                    "disposition": disposition.value,
                    "evidence_generation": routed.evidence_generation,
                    "execution_id": (
                        None if routed.snapshot is None else routed.snapshot.execution_id
                    ),
                    "operation_id": identity.operation_id,
                }
            )
            return cancel_receipt_to_wire(
                ExecutorCancelReceipt(
                    acknowledged_cancel_generation=routed.acknowledged_cancel_generation,
                    disposition=disposition,
                    evidence_generation=routed.evidence_generation,
                    execution_id=(
                        None if routed.snapshot is None else routed.snapshot.execution_id
                    ),
                    receipt_sha256=receipt_sha256,
                )
            )
        if message_type == "seal_no_accept":
            retain_until = _timestamp(request, "retain_until")
            result = await self._store.seal_no_accept(
                identity=routing_identity_from_wire(request["identity"]),
                reason=_text(request, "reason"),
                close_generation=_integer(request, "close_generation"),
                retain_until=retain_until,
            )
            return no_accept_result_to_wire(result)
        if message_type == "read_output":
            if self._output_reader is None:
                raise ExecutionTicketRejected("executor output is unavailable")
            operation_id = _operation_id(request)
            stream = OutputStream(_text(request, "stream"))
            offset = _integer(request, "offset")
            maximum = _integer(request, "max_bytes")
            if offset < 0 or not 1 <= maximum <= MAX_OUTPUT_CHUNK_BYTES:
                raise ExecutorProtocolError("executor output cursor is invalid")
            return output_chunk_to_wire(
                await self._output_reader(operation_id, stream, offset, maximum)
            )
        raise ExecutorProtocolError("executor request type is unsupported")

    async def handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        request_id = "invalid"
        message_type = "invalid"
        try:
            peer_socket = writer.get_extra_info("socket")
            if peer_socket is None:
                raise ExecutorProtocolError("executor connection has no peer socket")
            require_peer(
                peer_socket,
                expected_uid=self._identity.expected_client_uid,
                expected_gid=self._identity.expected_client_gid,
            )
            request = await asyncio.wait_for(read_frame(reader), _READ_TIMEOUT_SECONDS)
            request_id_value = request.get("request_id")
            type_value = request.get("type")
            if isinstance(request_id_value, str):
                request_id = request_id_value
            if isinstance(type_value, str):
                message_type = type_value
            validate_request(request)
            response = success_response(request, await self.dispatch(request))
        except (ExecutionTicketRejected, ExecutionConflictError) as exc:
            code = (
                "execution_ticket_rejected"
                if isinstance(exc, ExecutionTicketRejected)
                else "execution_identity_conflict"
            )
            response = error_response(request_id, message_type, code=code)
        except (ExecutorProtocolError, ExecutionError, ExecutorStoreError, ValueError):
            response = error_response(request_id, message_type, code="executor_request_invalid")
        except asyncio.CancelledError:
            writer.close()
            await writer.wait_closed()
            raise
        except Exception:  # noqa: BLE001 - never disclose unexpected server exceptions.
            response = error_response(request_id, message_type, code="executor_request_failed")
        try:
            await asyncio.wait_for(write_frame(writer, response), _WRITE_TIMEOUT_SECONDS)
        except (OSError, TimeoutError, ExecutorProtocolError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()


async def start_executor_server(
    listener: socket.socket,
    service: ExecutionSupervisorService,
) -> asyncio.AbstractServer:
    if listener.family != socket.AF_UNIX or listener.type & socket.SOCK_STREAM == 0:
        raise ExecutorServerError("executor listener is not a Unix stream socket")
    listener.setblocking(False)
    return await asyncio.start_unix_server(service.handle_connection, sock=listener)


def inherited_listener() -> socket.socket:
    try:
        listen_pid = int(os.environ["LISTEN_PID"])
        listen_fds = int(os.environ["LISTEN_FDS"])
    except (KeyError, ValueError) as exc:
        raise ExecutorServerError("executor requires one systemd-inherited listener") from exc
    if listen_pid != os.getpid() or listen_fds != 1:
        raise ExecutorServerError("executor inherited-listener identity is invalid")
    listener = socket.socket(fileno=3)
    if listener.family != socket.AF_UNIX or listener.type & socket.SOCK_STREAM == 0:
        listener.detach()
        raise ExecutorServerError("executor inherited listener has the wrong type")
    return listener


def _operation_id(request: dict[str, object]) -> str:
    operation_id = _text(request, "operation_id")
    validate_identifier(operation_id, name="operation_id")
    return operation_id


def _text(value: dict[str, object], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str):
        raise ExecutorProtocolError(f"{name} must be text")
    return result


def _optional_text(value: dict[str, object], name: str) -> str | None:
    result = value.get(name)
    if result is not None and not isinstance(result, str):
        raise ExecutorProtocolError(f"{name} must be text or null")
    return result


def _integer(value: dict[str, object], name: str) -> int:
    result = value.get(name)
    if isinstance(result, bool) or not isinstance(result, int):
        raise ExecutorProtocolError(f"{name} must be an integer")
    return result


def _timestamp(value: dict[str, object], name: str) -> datetime:
    try:
        result = datetime.fromisoformat(_text(value, name))
    except ValueError as exc:
        raise ExecutorProtocolError(f"{name} must be a timestamp") from exc
    if result.tzinfo is None:
        raise ExecutorProtocolError(f"{name} must include a timezone")
    return result


def _cancel_disposition(
    routed: CancelRoutingDisposition,
    snapshot: ExecutorSnapshot | None,
) -> CancelDisposition:
    if routed is CancelRoutingDisposition.PENDING_PREACCEPT:
        return CancelDisposition.PENDING_PREACCEPT
    if routed is CancelRoutingDisposition.NO_ACCEPT_PROVEN:
        return CancelDisposition.NO_ACCEPT_PROVEN
    if snapshot is None or snapshot.cancel_disposition is None:
        raise ExecutorStoreError("accepted cancellation lacks a disposition")
    return snapshot.cancel_disposition


__all__ = [
    "ExecutionSupervisorService",
    "ExecutorServerError",
    "ExecutorServerIdentity",
    "inherited_listener",
    "start_executor_server",
]
