"""Closed, bounded framed-JSON protocol for the local executor UDS."""

from __future__ import annotations

import asyncio
import base64
import json
import socket
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from binnacle.domain.execution import (
    EXECUTOR_PROTOCOL_ID,
    EXECUTOR_PROTOCOL_VERSION,
    MAX_EXECUTOR_FRAME_BYTES,
    CancelDisposition,
    CancelRoutingDisposition,
    CancelRoutingResult,
    CreateReceiptDisposition,
    ExecutionStartDisposition,
    ExecutionStartReceipt,
    ExecutorCancelReceipt,
    ExecutorEvidenceState,
    ExecutorOutputChunk,
    ExecutorSnapshot,
    NoAcceptSealResult,
    OutputAvailability,
    OutputStream,
    TicketRoutingIdentity,
    canonical_timestamp,
)

_HEADER: Final = struct.Struct("!I")
_PEER_CREDENTIALS: Final = struct.Struct("3i")
_REQUEST_TYPES: Final = frozenset(
    {
        "hello",
        "start_execution",
        "get_execution",
        "read_output",
        "request_cancel",
        "seal_no_accept",
        "list_executions",
    }
)


class ExecutorProtocolError(RuntimeError):
    """A local executor protocol frame is malformed or incompatible."""


@dataclass(frozen=True, slots=True)
class PeerCredentials:
    pid: int
    uid: int
    gid: int

    def __post_init__(self) -> None:
        if min(self.pid, self.uid, self.gid) < 0:
            raise ExecutorProtocolError("peer credentials are invalid")


def encode_frame(value: Mapping[str, object]) -> bytes:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExecutorProtocolError("executor message is not canonical JSON data") from exc
    if not payload or len(payload) > MAX_EXECUTOR_FRAME_BYTES:
        raise ExecutorProtocolError("executor message exceeds the reviewed frame limit")
    return _HEADER.pack(len(payload)) + payload


async def read_frame(reader: asyncio.StreamReader) -> dict[str, object]:
    try:
        header = await reader.readexactly(_HEADER.size)
        (length,) = _HEADER.unpack(header)
        if length < 2 or length > MAX_EXECUTOR_FRAME_BYTES:
            raise ExecutorProtocolError("executor frame length is invalid")
        payload = await reader.readexactly(length)
        document = json.loads(payload.decode("utf-8"))
    except (asyncio.IncompleteReadError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutorProtocolError("executor frame is truncated or invalid") from exc
    if not isinstance(document, dict) or not all(isinstance(key, str) for key in document):
        raise ExecutorProtocolError("executor frame must contain one JSON object")
    return document


async def write_frame(writer: asyncio.StreamWriter, value: Mapping[str, object]) -> None:
    writer.write(encode_frame(value))
    await writer.drain()


def validate_request(value: Mapping[str, object]) -> None:
    message_type = _require_text(value, "type")
    if message_type not in _REQUEST_TYPES:
        raise ExecutorProtocolError("executor request type is unsupported")
    common = {"protocol_id", "protocol_version", "request_id", "type"}
    specific = {
        "hello": set(),
        "start_execution": {"ticket"},
        "get_execution": {"operation_id"},
        "read_output": {"operation_id", "stream", "offset", "max_bytes"},
        "request_cancel": {"identity", "cancel_generation", "execution_id"},
        "seal_no_accept": {
            "identity",
            "reason",
            "close_generation",
            "retain_until",
        },
        "list_executions": {"operation_ids"},
    }[message_type]
    if set(value) != common | specific:
        raise ExecutorProtocolError("executor request fields are not exact")
    if value["protocol_id"] != EXECUTOR_PROTOCOL_ID:
        raise ExecutorProtocolError("executor protocol identity is incompatible")
    if value["protocol_version"] != EXECUTOR_PROTOCOL_VERSION:
        raise ExecutorProtocolError("executor protocol version is incompatible")
    request_id = _require_text(value, "request_id")
    if not request_id or len(request_id) > 160:
        raise ExecutorProtocolError("executor request identity is invalid")


def request_envelope(request_id: str, message_type: str, **fields: object) -> dict[str, object]:
    value = {
        "protocol_id": EXECUTOR_PROTOCOL_ID,
        "protocol_version": EXECUTOR_PROTOCOL_VERSION,
        "request_id": request_id,
        "type": message_type,
        **fields,
    }
    validate_request(value)
    return value


def success_response(
    request: Mapping[str, object],
    result: Mapping[str, object] | list[object] | None,
) -> dict[str, object]:
    return {
        "protocol_id": EXECUTOR_PROTOCOL_ID,
        "protocol_version": EXECUTOR_PROTOCOL_VERSION,
        "request_id": _require_text(request, "request_id"),
        "type": f"{_require_text(request, 'type')}_result",
        "ok": True,
        "result": result,
        "error": None,
    }


def error_response(
    request_id: str,
    message_type: str,
    *,
    code: str,
) -> dict[str, object]:
    if not code or len(code) > 160:
        code = "executor_request_failed"
    return {
        "protocol_id": EXECUTOR_PROTOCOL_ID,
        "protocol_version": EXECUTOR_PROTOCOL_VERSION,
        "request_id": request_id[:160],
        "type": f"{message_type[:64]}_result",
        "ok": False,
        "result": None,
        "error": {"code": code},
    }


def validate_response(value: Mapping[str, object], *, request_id: str) -> None:
    if set(value) != {
        "protocol_id",
        "protocol_version",
        "request_id",
        "type",
        "ok",
        "result",
        "error",
    }:
        raise ExecutorProtocolError("executor response fields are not exact")
    if (
        value["protocol_id"] != EXECUTOR_PROTOCOL_ID
        or value["protocol_version"] != EXECUTOR_PROTOCOL_VERSION
        or value["request_id"] != request_id
    ):
        raise ExecutorProtocolError("executor response correlation is invalid")
    if not isinstance(value["ok"], bool):
        raise ExecutorProtocolError("executor response discriminator is invalid")
    if value["ok"]:
        if value["error"] is not None:
            raise ExecutorProtocolError("successful executor response carries an error")
    elif value["result"] is not None or not isinstance(value["error"], dict):
        raise ExecutorProtocolError("failed executor response shape is invalid")


def peer_credentials(sock: socket.socket) -> PeerCredentials:
    if not hasattr(socket, "SO_PEERCRED"):
        raise ExecutorProtocolError("Linux SO_PEERCRED is unavailable")
    raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, _PEER_CREDENTIALS.size)
    return PeerCredentials(*_PEER_CREDENTIALS.unpack(raw))


def require_peer(sock: socket.socket, *, expected_uid: int, expected_gid: int) -> PeerCredentials:
    observed = peer_credentials(sock)
    if observed.uid != expected_uid or observed.gid != expected_gid:
        raise ExecutorProtocolError("executor peer identity is not authorised")
    return observed


def routing_identity_to_wire(identity: TicketRoutingIdentity) -> dict[str, object]:
    return {
        "operation_id": identity.operation_id,
        "ticket_id": identity.ticket_id,
        "ticket_sha256": identity.ticket_sha256,
        "nonce_sha256": identity.nonce_sha256,
        "boot_id_digest": identity.boot_id_digest,
        "expires_at": canonical_timestamp(identity.expires_at),
        "monotonic_deadline_ns": identity.monotonic_deadline_ns,
    }


def routing_identity_from_wire(value: object) -> TicketRoutingIdentity:
    if not isinstance(value, dict) or set(value) != {
        "operation_id",
        "ticket_id",
        "ticket_sha256",
        "nonce_sha256",
        "boot_id_digest",
        "expires_at",
        "monotonic_deadline_ns",
    }:
        raise ExecutorProtocolError("ticket routing identity fields are invalid")
    try:
        expires_at = datetime.fromisoformat(_require_text(value, "expires_at"))
    except ValueError as exc:
        raise ExecutorProtocolError("ticket routing expiry is invalid") from exc
    return TicketRoutingIdentity(
        operation_id=_require_text(value, "operation_id"),
        ticket_id=_require_text(value, "ticket_id"),
        ticket_sha256=_require_text(value, "ticket_sha256"),
        nonce_sha256=_require_text(value, "nonce_sha256"),
        boot_id_digest=_require_text(value, "boot_id_digest"),
        expires_at=expires_at,
        monotonic_deadline_ns=_require_integer(value, "monotonic_deadline_ns"),
    )


def start_receipt_to_wire(value: ExecutionStartReceipt) -> dict[str, object]:
    return {
        "disposition": value.disposition.value,
        "execution_id": value.execution_id,
        "evidence_generation": value.evidence_generation,
        "accepted_at": (
            None if value.accepted_at is None else canonical_timestamp(value.accepted_at)
        ),
        "executor_reference": value.executor_reference,
        "no_accept_reference": value.no_accept_reference,
        "receipt_sha256": value.receipt_sha256,
    }


def start_receipt_from_wire(value: object) -> ExecutionStartReceipt:
    raw = _exact_object(
        value,
        {
            "disposition",
            "execution_id",
            "evidence_generation",
            "accepted_at",
            "executor_reference",
            "no_accept_reference",
            "receipt_sha256",
        },
        "start receipt",
    )
    accepted_at = _optional_datetime(raw, "accepted_at")
    return ExecutionStartReceipt(
        disposition=ExecutionStartDisposition(_require_text(raw, "disposition")),
        execution_id=_optional_text(raw, "execution_id"),
        evidence_generation=_require_integer(raw, "evidence_generation"),
        accepted_at=accepted_at,
        executor_reference=_optional_text(raw, "executor_reference"),
        no_accept_reference=_optional_text(raw, "no_accept_reference"),
        receipt_sha256=_require_text(raw, "receipt_sha256"),
    )


def snapshot_to_wire(value: ExecutorSnapshot) -> dict[str, object]:
    return {
        "operation_id": value.operation_id,
        "ticket_id": value.ticket_id,
        "ticket_sha256": value.ticket_sha256,
        "execution_id": value.execution_id,
        "state": value.state.value,
        "state_version": value.state_version,
        "evidence_generation": value.evidence_generation,
        "effective_cancel_generation": value.effective_cancel_generation,
        "acknowledged_cancel_generation": value.acknowledged_cancel_generation,
        "cancel_disposition": (
            None if value.cancel_disposition is None else value.cancel_disposition.value
        ),
        "launch_generation": value.launch_generation,
        "launch_committed_at": (
            None
            if value.launch_committed_at is None
            else canonical_timestamp(value.launch_committed_at)
        ),
        "create_receipt_disposition": value.create_receipt_disposition.value,
        "backend_reference": value.backend_reference,
        "backend_domain_identity_sha256": value.backend_domain_identity_sha256,
        "accepted_at": canonical_timestamp(value.accepted_at),
        "exit_code": value.exit_code,
        "exit_signal": value.exit_signal,
        "terminal_reason": value.terminal_reason,
        "descendants_stopped": value.descendants_stopped,
        "output_finalized": value.output_finalized,
        "cleanup_complete": value.cleanup_complete,
        "terminal_evidence_sha256": value.terminal_evidence_sha256,
        "cleanup_evidence_sha256": value.cleanup_evidence_sha256,
    }


def snapshot_from_wire(value: object) -> ExecutorSnapshot:
    expected = {
        "operation_id",
        "ticket_id",
        "ticket_sha256",
        "execution_id",
        "state",
        "state_version",
        "evidence_generation",
        "effective_cancel_generation",
        "acknowledged_cancel_generation",
        "cancel_disposition",
        "launch_generation",
        "launch_committed_at",
        "create_receipt_disposition",
        "backend_reference",
        "backend_domain_identity_sha256",
        "accepted_at",
        "exit_code",
        "exit_signal",
        "terminal_reason",
        "descendants_stopped",
        "output_finalized",
        "cleanup_complete",
        "terminal_evidence_sha256",
        "cleanup_evidence_sha256",
    }
    raw = _exact_object(value, expected, "snapshot")
    cancel_value = _optional_text(raw, "cancel_disposition")
    return ExecutorSnapshot(
        operation_id=_require_text(raw, "operation_id"),
        ticket_id=_require_text(raw, "ticket_id"),
        ticket_sha256=_require_text(raw, "ticket_sha256"),
        execution_id=_require_text(raw, "execution_id"),
        state=ExecutorEvidenceState(_require_text(raw, "state")),
        state_version=_require_integer(raw, "state_version"),
        evidence_generation=_require_integer(raw, "evidence_generation"),
        effective_cancel_generation=_require_integer(raw, "effective_cancel_generation"),
        acknowledged_cancel_generation=_require_integer(raw, "acknowledged_cancel_generation"),
        cancel_disposition=None if cancel_value is None else CancelDisposition(cancel_value),
        launch_generation=_require_integer(raw, "launch_generation"),
        launch_committed_at=_optional_datetime(raw, "launch_committed_at"),
        create_receipt_disposition=CreateReceiptDisposition(
            _require_text(raw, "create_receipt_disposition")
        ),
        backend_reference=_optional_text(raw, "backend_reference"),
        backend_domain_identity_sha256=_optional_text(raw, "backend_domain_identity_sha256"),
        accepted_at=_require_datetime(raw, "accepted_at"),
        exit_code=_optional_integer(raw, "exit_code"),
        exit_signal=_optional_integer(raw, "exit_signal"),
        terminal_reason=_optional_text(raw, "terminal_reason"),
        descendants_stopped=_require_boolean(raw, "descendants_stopped"),
        output_finalized=_require_boolean(raw, "output_finalized"),
        cleanup_complete=_require_boolean(raw, "cleanup_complete"),
        terminal_evidence_sha256=_optional_text(raw, "terminal_evidence_sha256"),
        cleanup_evidence_sha256=_optional_text(raw, "cleanup_evidence_sha256"),
    )


def cancel_routing_to_wire(value: CancelRoutingResult) -> dict[str, object]:
    return {
        "disposition": value.disposition.value,
        "acknowledged_cancel_generation": value.acknowledged_cancel_generation,
        "evidence_generation": value.evidence_generation,
        "snapshot": None if value.snapshot is None else snapshot_to_wire(value.snapshot),
        "no_accept_reference": value.no_accept_reference,
    }


def cancel_routing_from_wire(value: object) -> CancelRoutingResult:
    raw = _exact_object(
        value,
        {
            "disposition",
            "acknowledged_cancel_generation",
            "evidence_generation",
            "snapshot",
            "no_accept_reference",
        },
        "cancel routing result",
    )
    snapshot_value = raw["snapshot"]
    return CancelRoutingResult(
        disposition=CancelRoutingDisposition(_require_text(raw, "disposition")),
        acknowledged_cancel_generation=_require_integer(raw, "acknowledged_cancel_generation"),
        evidence_generation=_require_integer(raw, "evidence_generation"),
        snapshot=None if snapshot_value is None else snapshot_from_wire(snapshot_value),
        no_accept_reference=_optional_text(raw, "no_accept_reference"),
    )


def no_accept_result_to_wire(value: NoAcceptSealResult) -> dict[str, object]:
    return {
        "disposition": value.disposition.value,
        "acknowledged_cancel_generation": value.acknowledged_cancel_generation,
        "evidence_generation": value.evidence_generation,
        "snapshot": None if value.snapshot is None else snapshot_to_wire(value.snapshot),
        "seal_reference": value.seal_reference,
        "executor_reference": value.executor_reference,
        "receipt_sha256": value.receipt_sha256,
    }


def no_accept_result_from_wire(value: object) -> NoAcceptSealResult:
    raw = _exact_object(
        value,
        {
            "disposition",
            "acknowledged_cancel_generation",
            "evidence_generation",
            "snapshot",
            "seal_reference",
            "executor_reference",
            "receipt_sha256",
        },
        "no-accept result",
    )
    snapshot_value = raw["snapshot"]
    return NoAcceptSealResult(
        disposition=ExecutionStartDisposition(_require_text(raw, "disposition")),
        acknowledged_cancel_generation=_require_integer(raw, "acknowledged_cancel_generation"),
        evidence_generation=_require_integer(raw, "evidence_generation"),
        snapshot=None if snapshot_value is None else snapshot_from_wire(snapshot_value),
        seal_reference=_optional_text(raw, "seal_reference"),
        executor_reference=_optional_text(raw, "executor_reference"),
        receipt_sha256=_require_text(raw, "receipt_sha256"),
    )


def cancel_receipt_to_wire(value: ExecutorCancelReceipt) -> dict[str, object]:
    return {
        "acknowledged_cancel_generation": value.acknowledged_cancel_generation,
        "disposition": value.disposition.value,
        "evidence_generation": value.evidence_generation,
        "execution_id": value.execution_id,
        "receipt_sha256": value.receipt_sha256,
    }


def cancel_receipt_from_wire(value: object) -> ExecutorCancelReceipt:
    raw = _exact_object(
        value,
        {
            "acknowledged_cancel_generation",
            "disposition",
            "evidence_generation",
            "execution_id",
            "receipt_sha256",
        },
        "cancel receipt",
    )
    return ExecutorCancelReceipt(
        acknowledged_cancel_generation=_require_integer(raw, "acknowledged_cancel_generation"),
        disposition=CancelDisposition(_require_text(raw, "disposition")),
        evidence_generation=_require_integer(raw, "evidence_generation"),
        execution_id=_optional_text(raw, "execution_id"),
        receipt_sha256=_require_text(raw, "receipt_sha256"),
    )


def output_chunk_to_wire(value: ExecutorOutputChunk) -> dict[str, object]:
    return {
        "operation_id": value.operation_id,
        "execution_id": value.execution_id,
        "stream": value.stream.value,
        "offset": value.offset,
        "next_offset": value.next_offset,
        "data_base64": base64.b64encode(value.data).decode("ascii"),
        "eof": value.eof,
        "availability": value.availability.value,
        "stream_sha256": value.stream_sha256,
    }


def output_chunk_from_wire(value: object) -> ExecutorOutputChunk:
    raw = _exact_object(
        value,
        {
            "operation_id",
            "execution_id",
            "stream",
            "offset",
            "next_offset",
            "data_base64",
            "eof",
            "availability",
            "stream_sha256",
        },
        "output chunk",
    )
    try:
        data = base64.b64decode(_require_text(raw, "data_base64"), validate=True)
    except ValueError as exc:
        raise ExecutorProtocolError("output chunk encoding is invalid") from exc
    return ExecutorOutputChunk(
        operation_id=_require_text(raw, "operation_id"),
        execution_id=_require_text(raw, "execution_id"),
        stream=OutputStream(_require_text(raw, "stream")),
        offset=_require_integer(raw, "offset"),
        next_offset=_require_integer(raw, "next_offset"),
        data=data,
        eof=_require_boolean(raw, "eof"),
        availability=OutputAvailability(_require_text(raw, "availability")),
        stream_sha256=_optional_text(raw, "stream_sha256"),
    )


def _exact_object(value: object, expected: set[str], name: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ExecutorProtocolError(f"{name} fields are not exact")
    return value


def _require_text(value: Mapping[str, object], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str):
        raise ExecutorProtocolError(f"{name} must be text")
    return result


def _optional_text(value: Mapping[str, object], name: str) -> str | None:
    result = value.get(name)
    if result is not None and not isinstance(result, str):
        raise ExecutorProtocolError(f"{name} must be text or null")
    return result


def _require_integer(value: Mapping[str, object], name: str) -> int:
    result = value.get(name)
    if isinstance(result, bool) or not isinstance(result, int):
        raise ExecutorProtocolError(f"{name} must be an integer")
    return result


def _optional_integer(value: Mapping[str, object], name: str) -> int | None:
    result = value.get(name)
    if result is None:
        return None
    if isinstance(result, bool) or not isinstance(result, int):
        raise ExecutorProtocolError(f"{name} must be an integer or null")
    return result


def _require_boolean(value: Mapping[str, object], name: str) -> bool:
    result = value.get(name)
    if not isinstance(result, bool):
        raise ExecutorProtocolError(f"{name} must be a boolean")
    return result


def _require_datetime(value: Mapping[str, object], name: str) -> datetime:
    text = _require_text(value, name)
    try:
        result = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ExecutorProtocolError(f"{name} is not a timestamp") from exc
    if result.tzinfo is None:
        raise ExecutorProtocolError(f"{name} must include a timezone")
    return result


def _optional_datetime(value: Mapping[str, object], name: str) -> datetime | None:
    return None if value.get(name) is None else _require_datetime(value, name)


__all__ = [
    "ExecutorProtocolError",
    "PeerCredentials",
    "cancel_receipt_from_wire",
    "cancel_receipt_to_wire",
    "cancel_routing_from_wire",
    "cancel_routing_to_wire",
    "encode_frame",
    "error_response",
    "no_accept_result_from_wire",
    "no_accept_result_to_wire",
    "output_chunk_from_wire",
    "output_chunk_to_wire",
    "peer_credentials",
    "read_frame",
    "request_envelope",
    "require_peer",
    "routing_identity_from_wire",
    "routing_identity_to_wire",
    "snapshot_from_wire",
    "snapshot_to_wire",
    "start_receipt_from_wire",
    "start_receipt_to_wire",
    "success_response",
    "validate_request",
    "validate_response",
    "write_frame",
]
