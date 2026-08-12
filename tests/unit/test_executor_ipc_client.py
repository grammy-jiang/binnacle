"""Focused unit tests for the bounded executor IPC client."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable, Mapping
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from tests.phase7_support import NOW, SHA_A, SHA_B, SHA_C, execution_ticket

from binnacle.adapters.executor_ipc import client as client_module
from binnacle.adapters.executor_ipc.client import (
    ExecutorClient,
    ExecutorClientError,
    ExecutorClientSettings,
)
from binnacle.domain.execution import (
    EXECUTOR_PROTOCOL_ID,
    EXECUTOR_PROTOCOL_VERSION,
    CancelDisposition,
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
)
from binnacle.executor.protocol import (
    ExecutorProtocolError,
    PeerCredentials,
    cancel_receipt_to_wire,
    error_response,
    no_accept_result_to_wire,
    output_chunk_to_wire,
    snapshot_to_wire,
    start_receipt_to_wire,
    success_response,
)


def _settings() -> ExecutorClientSettings:
    return ExecutorClientSettings(
        socket_path=Path("/run/binnacle-executor/test.sock"),
        expected_peer_uid=1001,
        expected_peer_gid=1002,
    )


def _snapshot() -> ExecutorSnapshot:
    ticket = execution_ticket()
    return ExecutorSnapshot(
        operation_id=ticket.operation_id,
        ticket_id=ticket.ticket_id,
        ticket_sha256=ticket.ticket_sha256,
        execution_id="execution-fixture",
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


class _RecordingWriter:
    def __init__(self, *, peer_socket: object | None = object()) -> None:
        self.peer_socket = peer_socket
        self.closed = False
        self.waited = False

    def get_extra_info(self, name: str) -> object | None:
        assert name == "socket"
        return self.peer_socket

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        self.waited = True


ResponseFactory = Callable[[dict[str, object]], dict[str, object]]


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    response_factory: ResponseFactory,
    *,
    peer_socket: object | None = object(),
) -> tuple[_RecordingWriter, list[dict[str, object]], list[tuple[int, int]]]:
    reader = asyncio.StreamReader()
    writer = _RecordingWriter(peer_socket=peer_socket)
    requests: list[dict[str, object]] = []
    peer_checks: list[tuple[int, int]] = []

    async def open_connection(
        *_args: object, **_kwargs: object
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return reader, cast(asyncio.StreamWriter, writer)

    def require_test_peer(
        _sock: socket.socket,
        *,
        expected_uid: int,
        expected_gid: int,
    ) -> PeerCredentials:
        peer_checks.append((expected_uid, expected_gid))
        return PeerCredentials(pid=123, uid=expected_uid, gid=expected_gid)

    async def record_frame(
        _writer: asyncio.StreamWriter,
        value: Mapping[str, object],
    ) -> None:
        requests.append(dict(value))

    async def provide_frame(_reader: asyncio.StreamReader) -> dict[str, object]:
        assert requests
        return response_factory(requests[-1])

    monkeypatch.setattr(asyncio, "open_unix_connection", open_connection)
    monkeypatch.setattr(client_module, "require_peer", require_test_peer)
    monkeypatch.setattr(client_module, "write_frame", record_frame)
    monkeypatch.setattr(client_module, "read_frame", provide_frame)
    return writer, requests, peer_checks


@pytest.mark.anyio
async def test_hello_exchange_authenticates_peer_correlates_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result: dict[str, object] = {
        "protocol_id": EXECUTOR_PROTOCOL_ID,
        "protocol_version": EXECUTOR_PROTOCOL_VERSION,
        "build_sha256": SHA_B,
        "profile_sha256": SHA_C,
        "supervisor_instance_id": "supervisor-fixture",
        "supervisor_generation": 7,
        "backend_ready": False,
        "readiness": "ready",
    }
    writer, requests, peer_checks = _install_transport(
        monkeypatch,
        lambda request: success_response(request, result),
    )

    hello = await ExecutorClient(_settings()).hello()

    assert hello.supervisor_generation == 7
    assert hello.backend_ready is False
    assert requests[0]["type"] == "hello"
    assert str(requests[0]["request_id"]).startswith("req_")
    assert peer_checks == [(1001, 1002)]
    assert writer.closed is True
    assert writer.waited is True


@pytest.mark.anyio
async def test_exchange_maps_protocol_failure_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, _, _ = _install_transport(
        monkeypatch,
        lambda _request: (_ for _ in ()).throw(ExecutorProtocolError("malformed response")),
    )

    with pytest.raises(ExecutorClientError, match="failed closed"):
        await ExecutorClient(_settings()).hello()

    assert writer.closed is True
    assert writer.waited is True


@pytest.mark.anyio
async def test_exchange_rejects_server_error_and_wrong_response_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_transport(
        monkeypatch,
        lambda request: error_response(
            str(request["request_id"]),
            str(request["type"]),
            code="execution_ticket_rejected",
        ),
    )
    with pytest.raises(ExecutorClientError, match="execution_ticket_rejected"):
        await ExecutorClient(_settings()).hello()

    def wrong_type(request: dict[str, object]) -> dict[str, object]:
        response = success_response(request, {})
        response["type"] = "get_execution_result"
        return response

    _install_transport(monkeypatch, wrong_type)
    with pytest.raises(ExecutorClientError, match="response type is invalid"):
        await ExecutorClient(_settings()).hello()

    _install_transport(
        monkeypatch,
        lambda request: {"request_id": request["request_id"]},
    )
    with pytest.raises(ExecutorClientError, match="failed closed"):
        await ExecutorClient(_settings()).hello()


class _ResultClient(ExecutorClient):
    def __init__(self, responses: Mapping[str, object]) -> None:
        super().__init__(_settings())
        self.responses = responses
        self.requests: list[tuple[str, dict[str, object]]] = []

    async def _exchange(self, message_type: str, **fields: object) -> object:
        self.requests.append((message_type, fields))
        return self.responses[message_type]


@pytest.mark.anyio
async def test_typed_operations_decode_exact_evidence_and_encode_fields() -> None:
    ticket = execution_ticket()
    snapshot = _snapshot()
    start_receipt = ExecutionStartReceipt(
        disposition=ExecutionStartDisposition.ACCEPTED_EXECUTION,
        execution_id=snapshot.execution_id,
        evidence_generation=2,
        accepted_at=NOW,
        executor_reference="executor-reference",
        no_accept_reference=None,
        receipt_sha256=SHA_A,
    )
    cancel_receipt = ExecutorCancelReceipt(
        acknowledged_cancel_generation=3,
        disposition=CancelDisposition.SIGNAL_PENDING,
        evidence_generation=4,
        execution_id=snapshot.execution_id,
        receipt_sha256=SHA_B,
    )
    seal_result = NoAcceptSealResult(
        disposition=ExecutionStartDisposition.NO_ACCEPT_PROVEN,
        acknowledged_cancel_generation=3,
        evidence_generation=5,
        snapshot=None,
        seal_reference="seal-reference",
        executor_reference=None,
        receipt_sha256=SHA_C,
    )
    output = ExecutorOutputChunk(
        operation_id=ticket.operation_id,
        execution_id=snapshot.execution_id,
        stream=OutputStream.STDOUT,
        offset=4,
        next_offset=7,
        data=b"out",
        eof=True,
        availability=OutputAvailability.AVAILABLE,
        stream_sha256=SHA_A,
    )
    client = _ResultClient(
        {
            "start_execution": start_receipt_to_wire(start_receipt),
            "get_execution": snapshot_to_wire(snapshot),
            "read_output": output_chunk_to_wire(output),
            "request_cancel": cancel_receipt_to_wire(cancel_receipt),
            "seal_no_accept": no_accept_result_to_wire(seal_result),
            "list_executions": [snapshot_to_wire(snapshot)],
        }
    )
    retain_until = NOW + timedelta(hours=1)

    assert await client.start(ticket) == start_receipt
    assert await client.get(ticket.operation_id) == snapshot
    assert await client.read_output(ticket.operation_id, OutputStream.STDOUT, 4, 1024) == output
    assert await client.cancel(ticket.routing_identity, 3, snapshot.execution_id) == cancel_receipt
    assert (
        await client.seal_no_accept(
            ticket.routing_identity,
            "application_runtime_lost",
            3,
            retain_until,
        )
        == seal_result
    )
    assert await client.list((ticket.operation_id,)) == (snapshot,)

    request_fields = dict(client.requests)
    assert request_fields["request_cancel"]["cancel_generation"] == 3
    assert request_fields["request_cancel"]["execution_id"] == snapshot.execution_id
    assert request_fields["read_output"]["stream"] == "stdout"
    assert request_fields["seal_no_accept"]["retain_until"] == retain_until.isoformat()
    assert request_fields["list_executions"]["operation_ids"] == [ticket.operation_id]


@pytest.mark.anyio
async def test_typed_operations_map_all_invalid_evidence_to_client_error() -> None:
    ticket = execution_ticket()
    client = _ResultClient(
        {
            "hello": {
                "protocol_id": EXECUTOR_PROTOCOL_ID,
                "protocol_version": EXECUTOR_PROTOCOL_VERSION,
                "build_sha256": SHA_B,
                "profile_sha256": SHA_C,
                "supervisor_instance_id": "supervisor-fixture",
                "supervisor_generation": 1,
                "backend_ready": False,
                "readiness": "invalid-readiness",
            },
            "start_execution": {},
            "get_execution": {},
            "read_output": {},
            "request_cancel": {},
            "seal_no_accept": {},
            "list_executions": [{}],
        }
    )

    calls = (
        client.hello(),
        client.start(ticket),
        client.get(ticket.operation_id),
        client.read_output(ticket.operation_id, OutputStream.STDOUT, 0, 1024),
        client.cancel(ticket.routing_identity, 1),
        client.seal_no_accept(
            ticket.routing_identity,
            "application_runtime_lost",
            1,
            NOW + timedelta(hours=1),
        ),
        client.list((ticket.operation_id,)),
    )
    for call in calls:
        with pytest.raises(ExecutorClientError, match="invalid evidence"):
            await call


@pytest.mark.anyio
async def test_list_bounds_and_shape_fail_closed_before_decoding() -> None:
    client = _ResultClient({"list_executions": {"unexpected": "object"}})

    with pytest.raises(ExecutorClientError, match="reviewed limit"):
        await client.list(tuple(f"op-{index}" for index in range(257)))
    assert client.requests == []

    with pytest.raises(ExecutorClientError, match="list response is invalid"):
        await client.list(("op-fixture",))


@pytest.mark.parametrize(
    "values, message",
    [
        ({"expected_peer_uid": -1}, "peer identity"),
        ({"socket_path": Path("relative.sock")}, "absolute"),
        ({"connect_timeout_seconds": 0.01}, "connect timeout"),
        ({"request_timeout_seconds": 61.0}, "request timeout"),
    ],
)
def test_client_settings_reject_unsafe_values(
    values: dict[str, object],
    message: str,
) -> None:
    arguments: dict[str, object] = {
        "socket_path": Path("/run/binnacle-executor/test.sock"),
        "expected_peer_uid": 1001,
        "expected_peer_gid": 1002,
        **values,
    }
    with pytest.raises(ExecutorClientError, match=message):
        ExecutorClientSettings(**arguments)  # type: ignore[arg-type]
