"""Closed wire-contract tests for the privileged broker protocol."""

from __future__ import annotations

import asyncio
import copy
import socket
import struct
from typing import cast

import pytest
from tests.phase9_support import (
    acceptance_receipt,
    binding_snapshot,
    controlled_restart_intent_and_ticket,
    privileged_ticket,
)

from binnacle.domain.privileged import (
    MAX_PRIVILEGED_FRAME_BYTES,
    BrokerAcceptanceState,
    BrokerBindingSnapshot,
    BrokerExecutionState,
    BrokerRestartCheckpointState,
    BrokerRestartOutcome,
    PrivilegedEffectKnowledge,
    PrivilegedError,
    PrivilegedTicket,
)
from binnacle.privileged_broker.protocol import (
    PeerCredentials,
    PrivilegedProtocolError,
    acceptance_receipt_from_wire,
    acceptance_receipt_to_wire,
    binding_snapshot_from_wire,
    binding_snapshot_to_wire,
    encode_frame,
    error_response,
    peer_credentials,
    read_frame,
    request_envelope,
    require_peer,
    restart_checkpoint_intent_from_wire,
    restart_checkpoint_intent_to_wire,
    routing_identity_from_wire,
    routing_identity_to_wire,
    success_response,
    validate_request,
    validate_response,
    write_frame,
)


def test_ticket_and_evidence_codecs_round_trip_exactly() -> None:
    ticket = privileged_ticket()
    assert PrivilegedTicket.from_wire(ticket.to_wire()) == ticket
    assert routing_identity_from_wire(routing_identity_to_wire(ticket.routing_identity)) == (
        ticket.routing_identity
    )
    receipt = acceptance_receipt()
    assert acceptance_receipt_from_wire(acceptance_receipt_to_wire(receipt)) == receipt
    snapshot = binding_snapshot()
    assert binding_snapshot_from_wire(binding_snapshot_to_wire(snapshot)) == snapshot

    tampered = ticket.to_wire()
    tampered["ticket_sha256"] = "0" * 64
    with pytest.raises(PrivilegedError, match="digest"):
        PrivilegedTicket.from_wire(tampered)


def test_request_and_response_envelopes_are_closed_and_correlated() -> None:
    request = request_envelope("req-fixture", "hello")
    validate_request(request)
    response = success_response(request, {"readiness": "disabled"})
    validate_response(response, request_id="req-fixture")

    for invalid in (
        {**request, "extra": True},
        {**request, "protocol_version": "future"},
        {**request, "type": "shell"},
    ):
        with pytest.raises(PrivilegedProtocolError):
            validate_request(invalid)
    with pytest.raises(PrivilegedProtocolError, match="correlation"):
        validate_response(response, request_id="different")


@pytest.mark.anyio
async def test_frame_codec_rejects_truncation_non_object_and_oversize() -> None:
    value = request_envelope("req-fixture", "hello")
    encoded = encode_frame(value)
    reader = asyncio.StreamReader()
    reader.feed_data(encoded)
    reader.feed_eof()
    assert await read_frame(reader) == value

    for payload in (b"[]", b"{"):
        invalid = asyncio.StreamReader()
        invalid.feed_data(struct.pack("!I", len(payload)) + payload)
        invalid.feed_eof()
        with pytest.raises(PrivilegedProtocolError):
            await read_frame(invalid)

    with pytest.raises(PrivilegedProtocolError, match="frame limit"):
        encode_frame({"payload": "x" * MAX_PRIVILEGED_FRAME_BYTES})

    invalid_length = asyncio.StreamReader()
    invalid_length.feed_data(struct.pack("!I", 1) + b"{")
    invalid_length.feed_eof()
    with pytest.raises(PrivilegedProtocolError, match="length"):
        await read_frame(invalid_length)

    for payload in (
        b'{"type":"hello","type":"different"}',
        b'{"value":NaN}',
        (b'{"nested":' * 12) + b"null" + (b"}" * 12),
    ):
        invalid_json = asyncio.StreamReader()
        invalid_json.feed_data(struct.pack("!I", len(payload)) + payload)
        invalid_json.feed_eof()
        with pytest.raises(PrivilegedProtocolError):
            await read_frame(invalid_json)

    with pytest.raises(PrivilegedProtocolError, match="object exceeds"):
        encode_frame({str(index): index for index in range(257)})


class _FrameWriter:
    def __init__(self) -> None:
        self.data = b""
        self.drained = False

    def write(self, data: bytes) -> None:
        self.data += data

    async def drain(self) -> None:
        self.drained = True


@pytest.mark.anyio
async def test_write_frame_emits_one_bounded_document() -> None:
    writer = _FrameWriter()
    await write_frame(cast(asyncio.StreamWriter, writer), request_envelope("req", "hello"))
    assert writer.drained is True
    assert struct.unpack("!I", writer.data[:4])[0] == len(writer.data) - 4


def test_receipt_and_snapshot_decoders_reject_changed_or_extra_evidence() -> None:
    receipt = acceptance_receipt_to_wire(acceptance_receipt())
    receipt["receipt_sha256"] = "0" * 64
    with pytest.raises(PrivilegedProtocolError, match="digest"):
        acceptance_receipt_from_wire(receipt)

    snapshot = binding_snapshot_to_wire(binding_snapshot())
    snapshot["unknown"] = None
    with pytest.raises(PrivilegedProtocolError, match="fields"):
        binding_snapshot_from_wire(snapshot)


def test_protocol_rejects_invalid_scalars_and_response_shapes() -> None:
    with pytest.raises(PrivilegedProtocolError, match="credentials"):
        PeerCredentials(pid=-1, uid=0, gid=0)
    with pytest.raises(PrivilegedProtocolError, match="unsupported"):
        encode_frame({"invalid": {object()}})

    request = request_envelope("req", "hello")
    invalid_requests = (
        {**request, "protocol_id": "other"},
        {**request, "request_id": ""},
        {**request, "request_id": "x" * 161},
    )
    for invalid in invalid_requests:
        with pytest.raises(PrivilegedProtocolError):
            validate_request(invalid)

    success = success_response(request, None)
    invalid_responses = (
        {**success, "extra": None},
        {**success, "ok": "yes"},
        {**success, "error": {"code": "wrong"}},
        {**success, "ok": False, "result": {}, "error": {"code": "failed"}},
    )
    for invalid in invalid_responses:
        with pytest.raises(PrivilegedProtocolError):
            validate_response(invalid, request_id="req")
    assert error_response("r" * 200, "m" * 100, code="")["error"] == {
        "code": "privileged_request_failed"
    }


class _PeerSocket:
    def __init__(self, *, pid: int = 10, uid: int = 1001, gid: int = 1002) -> None:
        self.value = struct.pack("3i", pid, uid, gid)

    def getsockopt(self, level: int, option: int, size: int) -> bytes:
        assert (level, option, size) == (socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        return self.value


def test_peer_credentials_require_exact_primary_identity() -> None:
    peer = cast(socket.socket, _PeerSocket())
    assert peer_credentials(peer) == PeerCredentials(pid=10, uid=1001, gid=1002)
    assert require_peer(peer, expected_uid=1001, expected_gid=1002).pid == 10
    with pytest.raises(PrivilegedProtocolError, match="not authorised"):
        require_peer(peer, expected_uid=1001, expected_gid=9999)


def test_wire_decoders_reject_invalid_enums_times_and_scalar_types() -> None:
    identity = routing_identity_to_wire(privileged_ticket().routing_identity)
    invalid_identities: tuple[object, ...] = (
        None,
        {**identity, "action": "host_reboot"},
        {**identity, "issued_at": "not-a-time"},
        {**identity, "expires_at": "2026-08-13T01:02:03"},
    )
    for invalid in invalid_identities:
        with pytest.raises(PrivilegedProtocolError):
            routing_identity_from_wire(invalid)

    receipt = acceptance_receipt_to_wire(acceptance_receipt())
    for invalid in (
        {**receipt, "disposition": "maybe"},
        {**receipt, "evidence_generation": True},
        {key: item for key, item in receipt.items() if key != "ticket_id"},
    ):
        with pytest.raises(PrivilegedProtocolError):
            acceptance_receipt_from_wire(invalid)

    snapshot = binding_snapshot_to_wire(binding_snapshot())
    for invalid in (
        {**snapshot, "acceptance_state": "maybe"},
        {**snapshot, "accepted_at": "2026-08-13T01:02:03"},
        {**snapshot, "acceptance_evidence_sha256": 7},
    ):
        with pytest.raises(PrivilegedProtocolError):
            binding_snapshot_from_wire(invalid)


def test_restart_checkpoint_and_terminal_binding_wire_round_trip() -> None:
    intent, ticket = controlled_restart_intent_and_ticket()
    document = restart_checkpoint_intent_to_wire(intent)
    assert restart_checkpoint_intent_from_wire(document) == intent

    binding = BrokerBindingSnapshot(
        identity=ticket.routing_identity,
        acceptance_state=BrokerAcceptanceState.ACCEPTED,
        evidence_generation=8,
        acceptance_evidence_sha256="a" * 64,
        execution_state=BrokerExecutionState.TERMINAL,
        effect_knowledge=PrivilegedEffectKnowledge.KNOWN_EFFECT,
        result_evidence_sha256="b" * 64,
        accepted_at=ticket.issued_at,
        sealed_at=None,
        closed_at=ticket.issued_at,
        last_reconciled_at=ticket.issued_at,
        restart_checkpoint_sha256=intent.intent_sha256,
        restart_checkpoint_state=BrokerRestartCheckpointState.TERMINAL,
        restart_outcome=BrokerRestartOutcome.CANDIDATE_READY,
        candidate_slot_id=intent.candidate_slot.slot_id,
        lkg_slot_id=intent.lkg_slot.slot_id,
        selected_runtime_slot_id=intent.candidate_slot.slot_id,
    )
    assert binding_snapshot_from_wire(binding_snapshot_to_wire(binding)) == binding


def test_restart_checkpoint_wire_rejects_nested_widening_and_tampering() -> None:
    intent, _ticket = controlled_restart_intent_and_ticket()
    document = restart_checkpoint_intent_to_wire(intent)
    invalid_documents: list[object] = [
        {**document, "extra": None},
        {**document, "intent_sha256": "0" * 64},
        {**document, "workspace_fence_version": True},
        {**document, "created_at": "2026-08-13T01:02:03"},
    ]

    preflight = cast(dict[str, object], copy.deepcopy(document["preflight"]))
    invalid_documents.append({**document, "preflight": {**preflight, "available": "yes"}})
    invalid_documents.append({**document, "preflight": {**preflight, "reason_codes": "none"}})
    invalid_documents.append({**document, "preflight": {**preflight, "predicted_impacts": [7]}})
    invalid_documents.append({**document, "preflight": {**preflight, "kind": "unreviewed"}})

    candidate = cast(dict[str, object], copy.deepcopy(document["candidate_slot"]))
    invalid_documents.append({**document, "candidate_slot": {**candidate, "extra": None}})
    invalid_documents.append({**document, "candidate_slot": {**candidate, "slot_generation": True}})
    invalid_documents.append({**document, "candidate_slot": {**candidate, "role": "lkg"}})
    invalid_documents.append(
        {**document, "candidate_slot": {**candidate, "completed_at": "not-a-time"}}
    )

    for invalid in invalid_documents:
        with pytest.raises(PrivilegedProtocolError):
            restart_checkpoint_intent_from_wire(invalid)
