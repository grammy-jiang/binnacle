from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Mapping
from typing import cast

import pytest
from tests.phase7_support import NOW, SHA_A, execution_ticket

from binnacle.domain.execution import (
    EXECUTOR_PROTOCOL_ID,
    EXECUTOR_PROTOCOL_VERSION,
    CancelRoutingDisposition,
    CancelRoutingResult,
    CreateReceiptDisposition,
    ExecutorEvidenceState,
    ExecutorOutputChunk,
    ExecutorSnapshot,
    OutputAvailability,
    OutputStream,
)
from binnacle.executor.protocol import (
    ExecutorProtocolError,
    PeerCredentials,
    cancel_receipt_from_wire,
    cancel_routing_from_wire,
    cancel_routing_to_wire,
    encode_frame,
    error_response,
    output_chunk_from_wire,
    output_chunk_to_wire,
    peer_credentials,
    read_frame,
    request_envelope,
    require_peer,
    routing_identity_from_wire,
    routing_identity_to_wire,
    snapshot_from_wire,
    snapshot_to_wire,
    success_response,
    validate_request,
    validate_response,
    write_frame,
)


def test_frame_round_trip_is_bounded_canonical_json() -> None:
    async def exercise() -> None:
        frame = encode_frame(request_envelope("request-1", "hello"))
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        reader.feed_eof()
        assert await read_frame(reader) == request_envelope("request-1", "hello")

    asyncio.run(exercise())


def test_request_rejects_unknown_fields() -> None:
    with pytest.raises(ExecutorProtocolError, match="fields are not exact"):
        request_envelope("request-1", "hello", authority="unexpected")


def test_ticket_routing_identity_round_trips() -> None:
    identity = execution_ticket().routing_identity
    assert routing_identity_from_wire(routing_identity_to_wire(identity)) == identity


def test_frame_rejects_oversize_body_before_reading_payload() -> None:
    async def exercise() -> None:
        reader = asyncio.StreamReader()
        reader.feed_data((1_048_577).to_bytes(4, "big"))
        reader.feed_eof()
        with pytest.raises(ExecutorProtocolError, match="length is invalid"):
            await read_frame(reader)

    asyncio.run(exercise())


def test_frame_encoding_rejects_non_json_and_oversize_values() -> None:
    with pytest.raises(ExecutorProtocolError, match="not canonical JSON"):
        encode_frame({"unsupported": object()})

    with pytest.raises(ExecutorProtocolError, match="reviewed frame limit"):
        encode_frame({"oversize": "x" * 1_048_576})


def test_write_frame_emits_one_encoded_frame_and_drains() -> None:
    class RecordingWriter:
        def __init__(self) -> None:
            self.data = b""
            self.drained = False

        def write(self, data: bytes) -> None:
            self.data += data

        async def drain(self) -> None:
            self.drained = True

    async def exercise() -> None:
        writer = RecordingWriter()
        request = request_envelope("request-write", "hello")
        await write_frame(cast(asyncio.StreamWriter, writer), request)
        assert writer.data == encode_frame(request)
        assert writer.drained is True

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "mutate, message",
    [
        ({"type": "unsupported"}, "type is unsupported"),
        ({"protocol_id": "other-protocol"}, "identity is incompatible"),
        ({"protocol_version": "2.0"}, "version is incompatible"),
        ({"request_id": ""}, "request identity is invalid"),
        ({"request_id": "r" * 161}, "request identity is invalid"),
    ],
)
def test_request_validation_rejects_incompatible_envelopes(
    mutate: dict[str, object],
    message: str,
) -> None:
    request = request_envelope("request-validate", "hello")
    request.update(mutate)
    with pytest.raises(ExecutorProtocolError, match=message):
        validate_request(request)


def test_error_response_bounds_untrusted_fields_and_uses_closed_code() -> None:
    response = error_response("r" * 200, "t" * 80, code="")

    assert response["request_id"] == "r" * 160
    assert response["type"] == f"{'t' * 64}_result"
    assert response["error"] == {"code": "executor_request_failed"}


@pytest.mark.parametrize(
    "response, message",
    [
        ({}, "fields are not exact"),
        (
            {
                "protocol_id": EXECUTOR_PROTOCOL_ID,
                "protocol_version": EXECUTOR_PROTOCOL_VERSION,
                "request_id": "other-request",
                "type": "hello_result",
                "ok": True,
                "result": None,
                "error": None,
            },
            "correlation is invalid",
        ),
        (
            {
                "protocol_id": EXECUTOR_PROTOCOL_ID,
                "protocol_version": EXECUTOR_PROTOCOL_VERSION,
                "request_id": "request-response",
                "type": "hello_result",
                "ok": 1,
                "result": None,
                "error": None,
            },
            "discriminator is invalid",
        ),
        (
            {
                "protocol_id": EXECUTOR_PROTOCOL_ID,
                "protocol_version": EXECUTOR_PROTOCOL_VERSION,
                "request_id": "request-response",
                "type": "hello_result",
                "ok": True,
                "result": None,
                "error": {"code": "contradiction"},
            },
            "carries an error",
        ),
        (
            {
                "protocol_id": EXECUTOR_PROTOCOL_ID,
                "protocol_version": EXECUTOR_PROTOCOL_VERSION,
                "request_id": "request-response",
                "type": "hello_result",
                "ok": False,
                "result": {"contradiction": True},
                "error": "not-an-object",
            },
            "failed executor response shape",
        ),
    ],
)
def test_response_validation_rejects_ambiguous_or_uncorrelated_shapes(
    response: Mapping[str, object],
    message: str,
) -> None:
    with pytest.raises(ExecutorProtocolError, match=message):
        validate_response(response, request_id="request-response")


def test_response_validation_accepts_exact_success_and_failure() -> None:
    request = request_envelope("request-response", "hello")
    success = success_response(request, {"ready": False})
    failure = error_response(
        "request-response",
        "hello",
        code="executor_request_failed",
    )

    validate_response(success, request_id="request-response")
    validate_response(failure, request_id="request-response")


def test_peer_credentials_are_kernel_derived_and_exactly_authorised() -> None:
    left, right = socket.socketpair()
    try:
        observed = peer_credentials(left)
        assert observed.pid > 0
        assert observed.uid == os.getuid()
        assert observed.gid == os.getgid()
        assert (
            require_peer(
                left,
                expected_uid=os.getuid(),
                expected_gid=os.getgid(),
            )
            == observed
        )
        with pytest.raises(ExecutorProtocolError, match="not authorised"):
            require_peer(
                left,
                expected_uid=os.getuid() + 1,
                expected_gid=os.getgid(),
            )
    finally:
        left.close()
        right.close()


def test_peer_credentials_fail_closed_without_linux_credential_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(socket, "SO_PEERCRED")
    with pytest.raises(ExecutorProtocolError, match="SO_PEERCRED is unavailable"):
        peer_credentials(cast(socket.socket, object()))


def test_negative_peer_credentials_are_rejected() -> None:
    with pytest.raises(ExecutorProtocolError, match="credentials are invalid"):
        PeerCredentials(pid=1, uid=-1, gid=1)


def test_routing_identity_rejects_wrong_shape_and_invalid_expiry() -> None:
    with pytest.raises(ExecutorProtocolError, match="fields are invalid"):
        routing_identity_from_wire({"operation_id": "op-only"})

    wire = routing_identity_to_wire(execution_ticket().routing_identity)
    wire["expires_at"] = "not-a-timestamp"
    with pytest.raises(ExecutorProtocolError, match="expiry is invalid"):
        routing_identity_from_wire(wire)


def _snapshot() -> ExecutorSnapshot:
    ticket = execution_ticket()
    return ExecutorSnapshot(
        operation_id=ticket.operation_id,
        ticket_id=ticket.ticket_id,
        ticket_sha256=ticket.ticket_sha256,
        execution_id="execution-protocol",
        state=ExecutorEvidenceState.ACCEPTED,
        state_version=1,
        evidence_generation=1,
        effective_cancel_generation=0,
        acknowledged_cancel_generation=0,
        cancel_disposition=None,
        launch_generation=0,
        launch_committed_at=None,
        create_receipt_disposition=CreateReceiptDisposition.NOT_ATTEMPTED,
        backend_reference=None,
        backend_domain_identity_sha256=None,
        accepted_at=NOW,
    )


def test_cancel_routing_result_round_trips_without_implicit_acceptance() -> None:
    result = CancelRoutingResult(
        disposition=CancelRoutingDisposition.PENDING_PREACCEPT,
        acknowledged_cancel_generation=2,
        evidence_generation=3,
        snapshot=None,
    )

    assert cancel_routing_from_wire(cancel_routing_to_wire(result)) == result


def test_output_chunk_rejects_non_base64_data() -> None:
    output = ExecutorOutputChunk(
        operation_id="op-protocol",
        execution_id="execution-protocol",
        stream=OutputStream.STDOUT,
        offset=0,
        next_offset=3,
        data=b"log",
        eof=False,
        availability=OutputAvailability.AVAILABLE,
        stream_sha256=SHA_A,
    )
    wire = output_chunk_to_wire(output)
    wire["data_base64"] = "not/base64!"

    with pytest.raises(ExecutorProtocolError, match="encoding is invalid"):
        output_chunk_from_wire(wire)


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("operation_id", 7, "must be text"),
        ("backend_reference", 7, "text or null"),
        ("state_version", True, "must be an integer"),
        ("exit_code", "zero", "integer or null"),
        ("descendants_stopped", "false", "must be a boolean"),
        ("accepted_at", "not-a-timestamp", "is not a timestamp"),
        ("accepted_at", "2026-08-13T10:00:00", "include a timezone"),
    ],
)
def test_snapshot_decoder_rejects_ambiguous_scalar_types(
    field: str,
    value: object,
    message: str,
) -> None:
    wire = snapshot_to_wire(_snapshot())
    wire[field] = value
    with pytest.raises(ExecutorProtocolError, match=message):
        snapshot_from_wire(wire)


def test_snapshot_decoder_accepts_exact_terminal_scalars() -> None:
    wire = snapshot_to_wire(_snapshot())
    wire.update(
        {
            "state": "exited",
            "exit_code": 0,
            "terminal_reason": "completed",
            "terminal_evidence_sha256": SHA_A,
        }
    )

    snapshot = snapshot_from_wire(wire)

    assert snapshot.state is ExecutorEvidenceState.EXITED
    assert snapshot.exit_code == 0
    assert snapshot.descendants_stopped is False


def test_exact_wire_decoders_reject_extra_or_missing_fields() -> None:
    with pytest.raises(ExecutorProtocolError, match="cancel receipt fields are not exact"):
        cancel_receipt_from_wire({})

    value: dict[str, object] = {
        "acknowledged_cancel_generation": 1,
        "disposition": "pending_preaccept",
        "evidence_generation": 1,
        "execution_id": 42,
        "receipt_sha256": SHA_A,
    }
    with pytest.raises(ExecutorProtocolError, match="text or null"):
        cancel_receipt_from_wire(value)
