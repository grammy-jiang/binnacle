"""Closed, bounded framed-JSON protocol for the privileged broker UDS."""

from __future__ import annotations

import asyncio
import json
import socket
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from binnacle.domain.privileged import (
    MAX_PRIVILEGED_FRAME_BYTES,
    PRIVILEGED_PROTOCOL_ID,
    PRIVILEGED_PROTOCOL_VERSION,
    BrokerAcceptanceDisposition,
    BrokerAcceptanceReceipt,
    BrokerAcceptanceState,
    BrokerBindingSnapshot,
    BrokerExecutionState,
    BrokerRestartCheckpointState,
    BrokerRestartOutcome,
    PrivilegedAction,
    PrivilegedEffectKnowledge,
    PrivilegedTicketRoutingIdentity,
    canonical_timestamp,
)
from binnacle.domain.privileged_observation import (
    RestartImpact,
    RestartPreflightKind,
    RestartPreflightReason,
    RestartPreflightResult,
    RuntimeSlotRole,
    RuntimeSlotState,
    VerifiedRuntimeSlot,
)
from binnacle.domain.privileged_restart import PrivilegedRestartCheckpointIntent

_HEADER: Final = struct.Struct("!I")
_PEER_CREDENTIALS: Final = struct.Struct("3i")
_MAX_JSON_DEPTH: Final = 8
_MAX_JSON_NODES: Final = 4_096
_MAX_CONTAINER_ITEMS: Final = 256
_REQUEST_TYPES: Final = frozenset({"hello", "start_privileged", "get_binding", "seal_no_accept"})


class PrivilegedProtocolError(RuntimeError):
    """A privileged broker frame is malformed or incompatible."""


@dataclass(frozen=True, slots=True)
class PeerCredentials:
    pid: int
    uid: int
    gid: int

    def __post_init__(self) -> None:
        if min(self.pid, self.uid, self.gid) < 0:
            raise PrivilegedProtocolError("privileged peer credentials are invalid")


def encode_frame(value: Mapping[str, object]) -> bytes:
    _validate_json_shape(value)
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PrivilegedProtocolError("privileged message is not canonical JSON data") from exc
    if not payload or len(payload) > MAX_PRIVILEGED_FRAME_BYTES:
        raise PrivilegedProtocolError("privileged message exceeds the reviewed frame limit")
    return _HEADER.pack(len(payload)) + payload


async def read_frame(reader: asyncio.StreamReader) -> dict[str, object]:
    try:
        header = await reader.readexactly(_HEADER.size)
        (length,) = _HEADER.unpack(header)
        if length < 2 or length > MAX_PRIVILEGED_FRAME_BYTES:
            raise PrivilegedProtocolError("privileged frame length is invalid")
        payload = await reader.readexactly(length)
        document = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_object_from_pairs,
            parse_constant=_reject_json_constant,
        )
    except (
        asyncio.IncompleteReadError,
        UnicodeDecodeError,
        RecursionError,
        ValueError,
    ) as exc:
        raise PrivilegedProtocolError("privileged frame is truncated or invalid") from exc
    if not isinstance(document, dict) or not all(isinstance(key, str) for key in document):
        raise PrivilegedProtocolError("privileged frame must contain one JSON object")
    _validate_json_shape(document)
    return document


async def write_frame(writer: asyncio.StreamWriter, value: Mapping[str, object]) -> None:
    writer.write(encode_frame(value))
    await writer.drain()


def validate_request(value: Mapping[str, object]) -> None:
    message_type = _text(value, "type")
    if message_type not in _REQUEST_TYPES:
        raise PrivilegedProtocolError("privileged request type is unsupported")
    common = {"protocol_id", "protocol_version", "request_id", "type"}
    specific = {
        "hello": set(),
        "start_privileged": {"restart_intent", "ticket"},
        "get_binding": {"operation_id"},
        "seal_no_accept": {
            "identity",
            "reason",
            "trusted_time_at",
            "retain_until",
        },
    }[message_type]
    if set(value) != common | specific:
        raise PrivilegedProtocolError("privileged request fields are not exact")
    if value["protocol_id"] != PRIVILEGED_PROTOCOL_ID:
        raise PrivilegedProtocolError("privileged protocol identity is incompatible")
    if value["protocol_version"] != PRIVILEGED_PROTOCOL_VERSION:
        raise PrivilegedProtocolError("privileged protocol version is incompatible")
    request_id = _text(value, "request_id")
    if not request_id or len(request_id) > 160:
        raise PrivilegedProtocolError("privileged request identity is invalid")


def request_envelope(request_id: str, message_type: str, **fields: object) -> dict[str, object]:
    value = {
        "protocol_id": PRIVILEGED_PROTOCOL_ID,
        "protocol_version": PRIVILEGED_PROTOCOL_VERSION,
        "request_id": request_id,
        "type": message_type,
        **fields,
    }
    validate_request(value)
    return value


def success_response(
    request: Mapping[str, object],
    result: Mapping[str, object] | None,
) -> dict[str, object]:
    return {
        "protocol_id": PRIVILEGED_PROTOCOL_ID,
        "protocol_version": PRIVILEGED_PROTOCOL_VERSION,
        "request_id": _text(request, "request_id"),
        "type": f"{_text(request, 'type')}_result",
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
        code = "privileged_request_failed"
    return {
        "protocol_id": PRIVILEGED_PROTOCOL_ID,
        "protocol_version": PRIVILEGED_PROTOCOL_VERSION,
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
        raise PrivilegedProtocolError("privileged response fields are not exact")
    if (
        value["protocol_id"] != PRIVILEGED_PROTOCOL_ID
        or value["protocol_version"] != PRIVILEGED_PROTOCOL_VERSION
        or value["request_id"] != request_id
    ):
        raise PrivilegedProtocolError("privileged response correlation is invalid")
    if not isinstance(value["ok"], bool):
        raise PrivilegedProtocolError("privileged response discriminator is invalid")
    if value["ok"]:
        if value["error"] is not None:
            raise PrivilegedProtocolError("successful privileged response carries an error")
    elif value["result"] is not None or not isinstance(value["error"], dict):
        raise PrivilegedProtocolError("failed privileged response shape is invalid")


def peer_credentials(sock: socket.socket) -> PeerCredentials:
    if not hasattr(socket, "SO_PEERCRED"):
        raise PrivilegedProtocolError("Linux SO_PEERCRED is unavailable")
    raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, _PEER_CREDENTIALS.size)
    return PeerCredentials(*_PEER_CREDENTIALS.unpack(raw))


def require_peer(sock: socket.socket, *, expected_uid: int, expected_gid: int) -> PeerCredentials:
    observed = peer_credentials(sock)
    if observed.uid != expected_uid or observed.gid != expected_gid:
        raise PrivilegedProtocolError("privileged peer identity is not authorised")
    return observed


def routing_identity_to_wire(identity: PrivilegedTicketRoutingIdentity) -> dict[str, object]:
    return {
        "operation_id": identity.operation_id,
        "ticket_id": identity.ticket_id,
        "ticket_sha256": identity.ticket_sha256,
        "ticket_nonce_sha256": identity.ticket_nonce_sha256,
        "action": identity.action.value,
        "target_profile_id": identity.target_profile_id,
        "target_profile_sha256": identity.target_profile_sha256,
        "broker_profile_sha256": identity.broker_profile_sha256,
        "request_fingerprint_sha256": identity.request_fingerprint_sha256,
        "current_state_binding_sha256": identity.current_state_binding_sha256,
        "policy_evidence_sha256": identity.policy_evidence_sha256,
        "issued_at": canonical_timestamp(identity.issued_at),
        "expires_at": canonical_timestamp(identity.expires_at),
    }


def routing_identity_from_wire(value: object) -> PrivilegedTicketRoutingIdentity:
    fields = {
        "operation_id",
        "ticket_id",
        "ticket_sha256",
        "ticket_nonce_sha256",
        "action",
        "target_profile_id",
        "target_profile_sha256",
        "broker_profile_sha256",
        "request_fingerprint_sha256",
        "current_state_binding_sha256",
        "policy_evidence_sha256",
        "issued_at",
        "expires_at",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise PrivilegedProtocolError("privileged routing identity fields are invalid")
    try:
        return PrivilegedTicketRoutingIdentity(
            operation_id=_text(value, "operation_id"),
            ticket_id=_text(value, "ticket_id"),
            ticket_sha256=_text(value, "ticket_sha256"),
            ticket_nonce_sha256=_text(value, "ticket_nonce_sha256"),
            action=PrivilegedAction(_text(value, "action")),
            target_profile_id=_text(value, "target_profile_id"),
            target_profile_sha256=_text(value, "target_profile_sha256"),
            broker_profile_sha256=_text(value, "broker_profile_sha256"),
            request_fingerprint_sha256=_text(value, "request_fingerprint_sha256"),
            current_state_binding_sha256=_text(value, "current_state_binding_sha256"),
            policy_evidence_sha256=_text(value, "policy_evidence_sha256"),
            issued_at=_timestamp(value, "issued_at"),
            expires_at=_timestamp(value, "expires_at"),
        )
    except ValueError as exc:
        raise PrivilegedProtocolError("privileged routing identity is invalid") from exc


def acceptance_receipt_to_wire(value: BrokerAcceptanceReceipt) -> dict[str, object]:
    return {
        "operation_id": value.operation_id,
        "ticket_id": value.ticket_id,
        "ticket_sha256": value.ticket_sha256,
        "disposition": value.disposition.value,
        "evidence_generation": value.evidence_generation,
        "effect_knowledge": value.effect_knowledge.value,
        "evidence_sha256": value.evidence_sha256,
        "receipt_sha256": value.receipt_sha256,
    }


def acceptance_receipt_from_wire(value: object) -> BrokerAcceptanceReceipt:
    fields = {
        "operation_id",
        "ticket_id",
        "ticket_sha256",
        "disposition",
        "evidence_generation",
        "effect_knowledge",
        "evidence_sha256",
        "receipt_sha256",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise PrivilegedProtocolError("privileged acceptance receipt fields are invalid")
    try:
        receipt = BrokerAcceptanceReceipt(
            operation_id=_text(value, "operation_id"),
            ticket_id=_text(value, "ticket_id"),
            ticket_sha256=_text(value, "ticket_sha256"),
            disposition=BrokerAcceptanceDisposition(_text(value, "disposition")),
            evidence_generation=_integer(value, "evidence_generation"),
            effect_knowledge=PrivilegedEffectKnowledge(_text(value, "effect_knowledge")),
            evidence_sha256=_text(value, "evidence_sha256"),
        )
    except ValueError as exc:
        raise PrivilegedProtocolError("privileged acceptance receipt is invalid") from exc
    if _text(value, "receipt_sha256") != receipt.receipt_sha256:
        raise PrivilegedProtocolError("privileged acceptance receipt digest does not match")
    return receipt


def binding_snapshot_to_wire(value: BrokerBindingSnapshot) -> dict[str, object]:
    return {
        "identity": routing_identity_to_wire(value.identity),
        "acceptance_state": value.acceptance_state.value,
        "evidence_generation": value.evidence_generation,
        "acceptance_evidence_sha256": value.acceptance_evidence_sha256,
        "execution_state": value.execution_state.value,
        "effect_knowledge": value.effect_knowledge.value,
        "result_evidence_sha256": value.result_evidence_sha256,
        "accepted_at": _optional_timestamp_to_wire(value.accepted_at),
        "sealed_at": _optional_timestamp_to_wire(value.sealed_at),
        "closed_at": _optional_timestamp_to_wire(value.closed_at),
        "last_reconciled_at": _optional_timestamp_to_wire(value.last_reconciled_at),
        "restart_checkpoint_sha256": value.restart_checkpoint_sha256,
        "restart_checkpoint_state": (
            None if value.restart_checkpoint_state is None else value.restart_checkpoint_state.value
        ),
        "restart_outcome": (None if value.restart_outcome is None else value.restart_outcome.value),
        "candidate_slot_id": value.candidate_slot_id,
        "lkg_slot_id": value.lkg_slot_id,
        "selected_runtime_slot_id": value.selected_runtime_slot_id,
    }


def binding_snapshot_from_wire(value: object) -> BrokerBindingSnapshot:
    fields = {
        "identity",
        "acceptance_state",
        "evidence_generation",
        "acceptance_evidence_sha256",
        "execution_state",
        "effect_knowledge",
        "result_evidence_sha256",
        "accepted_at",
        "sealed_at",
        "closed_at",
        "last_reconciled_at",
        "restart_checkpoint_sha256",
        "restart_checkpoint_state",
        "restart_outcome",
        "candidate_slot_id",
        "lkg_slot_id",
        "selected_runtime_slot_id",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise PrivilegedProtocolError("privileged binding snapshot fields are invalid")
    try:
        return BrokerBindingSnapshot(
            identity=routing_identity_from_wire(value["identity"]),
            acceptance_state=BrokerAcceptanceState(_text(value, "acceptance_state")),
            evidence_generation=_integer(value, "evidence_generation"),
            acceptance_evidence_sha256=_optional_text(value, "acceptance_evidence_sha256"),
            execution_state=BrokerExecutionState(_text(value, "execution_state")),
            effect_knowledge=PrivilegedEffectKnowledge(_text(value, "effect_knowledge")),
            result_evidence_sha256=_optional_text(value, "result_evidence_sha256"),
            accepted_at=_optional_timestamp(value, "accepted_at"),
            sealed_at=_optional_timestamp(value, "sealed_at"),
            closed_at=_optional_timestamp(value, "closed_at"),
            last_reconciled_at=_optional_timestamp(value, "last_reconciled_at"),
            restart_checkpoint_sha256=_optional_text(value, "restart_checkpoint_sha256"),
            restart_checkpoint_state=(
                None
                if value["restart_checkpoint_state"] is None
                else BrokerRestartCheckpointState(_text(value, "restart_checkpoint_state"))
            ),
            restart_outcome=(
                None
                if value["restart_outcome"] is None
                else BrokerRestartOutcome(_text(value, "restart_outcome"))
            ),
            candidate_slot_id=_optional_text(value, "candidate_slot_id"),
            lkg_slot_id=_optional_text(value, "lkg_slot_id"),
            selected_runtime_slot_id=_optional_text(value, "selected_runtime_slot_id"),
        )
    except ValueError as exc:
        raise PrivilegedProtocolError("privileged binding snapshot is invalid") from exc


def restart_checkpoint_intent_to_wire(
    value: PrivilegedRestartCheckpointIntent,
) -> dict[str, object]:
    return {
        "operation_id": value.operation_id,
        "ticket_id": value.ticket_id,
        "ticket_sha256": value.ticket_sha256,
        "service_profile_sha256": value.service_profile_sha256,
        "workspace_id": value.workspace_id,
        "workspace_fence_version": value.workspace_fence_version,
        "preflight": _preflight_to_wire(value.preflight),
        "candidate_slot": _runtime_slot_to_wire(value.candidate_slot),
        "lkg_slot": _runtime_slot_to_wire(value.lkg_slot),
        "restart_deadline_seconds": value.restart_deadline_seconds,
        "created_at": canonical_timestamp(value.created_at),
        "intent_sha256": value.intent_sha256,
    }


def restart_checkpoint_intent_from_wire(value: object) -> PrivilegedRestartCheckpointIntent:
    fields = {
        "operation_id",
        "ticket_id",
        "ticket_sha256",
        "service_profile_sha256",
        "workspace_id",
        "workspace_fence_version",
        "preflight",
        "candidate_slot",
        "lkg_slot",
        "restart_deadline_seconds",
        "created_at",
        "intent_sha256",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise PrivilegedProtocolError("restart checkpoint intent fields are invalid")
    try:
        intent = PrivilegedRestartCheckpointIntent(
            operation_id=_text(value, "operation_id"),
            ticket_id=_text(value, "ticket_id"),
            ticket_sha256=_text(value, "ticket_sha256"),
            service_profile_sha256=_text(value, "service_profile_sha256"),
            workspace_id=_text(value, "workspace_id"),
            workspace_fence_version=_integer(value, "workspace_fence_version"),
            preflight=_preflight_from_wire(value["preflight"]),
            candidate_slot=_runtime_slot_from_wire(value["candidate_slot"]),
            lkg_slot=_runtime_slot_from_wire(value["lkg_slot"]),
            restart_deadline_seconds=_integer(value, "restart_deadline_seconds"),
            created_at=_timestamp(value, "created_at"),
        )
    except ValueError as exc:
        raise PrivilegedProtocolError("restart checkpoint intent is invalid") from exc
    if _text(value, "intent_sha256") != intent.intent_sha256:
        raise PrivilegedProtocolError("restart checkpoint intent digest does not match")
    return intent


def _preflight_to_wire(value: RestartPreflightResult) -> dict[str, object]:
    return {
        "kind": value.kind.value,
        "available": value.available,
        "reason_codes": [item.value for item in value.reason_codes],
        "predicted_impacts": [item.value for item in value.predicted_impacts],
        "current_runtime_identity_sha256": value.current_runtime_identity_sha256,
        "current_service_observation_sha256": value.current_service_observation_sha256,
        "lkg_slot_identity_sha256": value.lkg_slot_identity_sha256,
        "candidate_slot_identity_sha256": value.candidate_slot_identity_sha256,
        "candidate_verification_sha256": value.candidate_verification_sha256,
        "outstanding_state_sha256": value.outstanding_state_sha256,
        "state_binding_sha256": value.state_binding_sha256,
        "observed_at": canonical_timestamp(value.observed_at),
    }


def _preflight_from_wire(value: object) -> RestartPreflightResult:
    fields = {
        "kind",
        "available",
        "reason_codes",
        "predicted_impacts",
        "current_runtime_identity_sha256",
        "current_service_observation_sha256",
        "lkg_slot_identity_sha256",
        "candidate_slot_identity_sha256",
        "candidate_verification_sha256",
        "outstanding_state_sha256",
        "state_binding_sha256",
        "observed_at",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise PrivilegedProtocolError("restart preflight fields are invalid")
    reasons = value["reason_codes"]
    impacts = value["predicted_impacts"]
    available = value["available"]
    if (
        not isinstance(reasons, list)
        or not all(isinstance(item, str) for item in reasons)
        or not isinstance(impacts, list)
        or not all(isinstance(item, str) for item in impacts)
        or not isinstance(available, bool)
    ):
        raise PrivilegedProtocolError("restart preflight collections are invalid")
    return RestartPreflightResult(
        kind=RestartPreflightKind(_text(value, "kind")),
        available=available,
        reason_codes=tuple(RestartPreflightReason(item) for item in reasons),
        predicted_impacts=tuple(RestartImpact(item) for item in impacts),
        current_runtime_identity_sha256=_optional_text(value, "current_runtime_identity_sha256"),
        current_service_observation_sha256=_text(value, "current_service_observation_sha256"),
        lkg_slot_identity_sha256=_optional_text(value, "lkg_slot_identity_sha256"),
        candidate_slot_identity_sha256=_optional_text(value, "candidate_slot_identity_sha256"),
        candidate_verification_sha256=_optional_text(value, "candidate_verification_sha256"),
        outstanding_state_sha256=_text(value, "outstanding_state_sha256"),
        state_binding_sha256=_text(value, "state_binding_sha256"),
        observed_at=_timestamp(value, "observed_at"),
    )


def _runtime_slot_to_wire(value: VerifiedRuntimeSlot) -> dict[str, object]:
    return {
        "slot_id": value.slot_id,
        "slot_generation": value.slot_generation,
        "slot_path": value.slot_path,
        "role": value.role.value,
        "state": value.state.value,
        "source_sha256": value.source_sha256,
        "environment_sha256": value.environment_sha256,
        "config_sha256": value.config_sha256,
        "policy_sha256": value.policy_sha256,
        "manifest_sha256": value.manifest_sha256,
        "service_definition_sha256": value.service_definition_sha256,
        "deployed_peer_set_sha256": value.deployed_peer_set_sha256,
        "migration_heads_sha256": value.migration_heads_sha256,
        "layout_sha256": value.layout_sha256,
        "candidate_verification_sha256": value.candidate_verification_sha256,
        "complete_manifest_sha256": value.complete_manifest_sha256,
        "byte_count": value.byte_count,
        "inode_count": value.inode_count,
        "completed_at": canonical_timestamp(value.completed_at),
    }


def _runtime_slot_from_wire(value: object) -> VerifiedRuntimeSlot:
    fields = {
        "slot_id",
        "slot_generation",
        "slot_path",
        "role",
        "state",
        "source_sha256",
        "environment_sha256",
        "config_sha256",
        "policy_sha256",
        "manifest_sha256",
        "service_definition_sha256",
        "deployed_peer_set_sha256",
        "migration_heads_sha256",
        "layout_sha256",
        "candidate_verification_sha256",
        "complete_manifest_sha256",
        "byte_count",
        "inode_count",
        "completed_at",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise PrivilegedProtocolError("restart runtime slot fields are invalid")
    return VerifiedRuntimeSlot(
        slot_id=_text(value, "slot_id"),
        slot_generation=_integer(value, "slot_generation"),
        slot_path=_text(value, "slot_path"),
        role=RuntimeSlotRole(_text(value, "role")),
        state=RuntimeSlotState(_text(value, "state")),
        source_sha256=_text(value, "source_sha256"),
        environment_sha256=_text(value, "environment_sha256"),
        config_sha256=_text(value, "config_sha256"),
        policy_sha256=_text(value, "policy_sha256"),
        manifest_sha256=_text(value, "manifest_sha256"),
        service_definition_sha256=_text(value, "service_definition_sha256"),
        deployed_peer_set_sha256=_text(value, "deployed_peer_set_sha256"),
        migration_heads_sha256=_text(value, "migration_heads_sha256"),
        layout_sha256=_text(value, "layout_sha256"),
        candidate_verification_sha256=_text(value, "candidate_verification_sha256"),
        complete_manifest_sha256=_text(value, "complete_manifest_sha256"),
        byte_count=_integer(value, "byte_count"),
        inode_count=_integer(value, "inode_count"),
        completed_at=_timestamp(value, "completed_at"),
    )


def _text(value: Mapping[str, object], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str):
        raise PrivilegedProtocolError(f"privileged {name} must be text")
    return result


def _optional_text(value: Mapping[str, object], name: str) -> str | None:
    result = value.get(name)
    if result is not None and not isinstance(result, str):
        raise PrivilegedProtocolError(f"privileged {name} must be text or null")
    return result


def _integer(value: Mapping[str, object], name: str) -> int:
    result = value.get(name)
    if isinstance(result, bool) or not isinstance(result, int):
        raise PrivilegedProtocolError(f"privileged {name} must be an integer")
    return result


def _timestamp(value: Mapping[str, object], name: str) -> datetime:
    try:
        result = datetime.fromisoformat(_text(value, name))
    except ValueError as exc:
        raise PrivilegedProtocolError(f"privileged {name} must be a timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise PrivilegedProtocolError(f"privileged {name} must include a timezone")
    return result


def _optional_timestamp(value: Mapping[str, object], name: str) -> datetime | None:
    return None if value.get(name) is None else _timestamp(value, name)


def _optional_timestamp_to_wire(value: datetime | None) -> str | None:
    return None if value is None else canonical_timestamp(value)


def _object_from_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate privileged JSON member")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-finite privileged JSON number: {value}")


def _validate_json_shape(value: object) -> None:
    pending = [(value, 0)]
    observed = 0
    while pending:
        current, depth = pending.pop()
        observed += 1
        if observed > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            raise PrivilegedProtocolError("privileged JSON structure exceeds its bound")
        if isinstance(current, Mapping):
            if len(current) > _MAX_CONTAINER_ITEMS or not all(
                isinstance(key, str) for key in current
            ):
                raise PrivilegedProtocolError("privileged JSON object exceeds its bound")
            pending.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            if len(current) > _MAX_CONTAINER_ITEMS:
                raise PrivilegedProtocolError("privileged JSON list exceeds its bound")
            pending.extend((item, depth + 1) for item in current)
        elif current is not None and not isinstance(current, str | int | float | bool):
            raise PrivilegedProtocolError("privileged JSON contains an unsupported value")


__all__ = [
    "PeerCredentials",
    "PrivilegedProtocolError",
    "acceptance_receipt_from_wire",
    "acceptance_receipt_to_wire",
    "binding_snapshot_from_wire",
    "binding_snapshot_to_wire",
    "encode_frame",
    "error_response",
    "read_frame",
    "request_envelope",
    "require_peer",
    "restart_checkpoint_intent_from_wire",
    "restart_checkpoint_intent_to_wire",
    "routing_identity_from_wire",
    "routing_identity_to_wire",
    "success_response",
    "validate_request",
    "validate_response",
    "write_frame",
]
