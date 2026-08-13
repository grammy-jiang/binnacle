"""Application-side privileged IPC client tests."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable, Mapping
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from tests.phase9_support import (
    NOW,
    SHA_B,
    SHA_C,
    acceptance_receipt,
    binding_snapshot,
    privileged_ticket,
)

from binnacle.adapters.privileged_ipc import client as client_module
from binnacle.adapters.privileged_ipc.client import (
    PrivilegedClient,
    PrivilegedClientError,
    PrivilegedClientSettings,
)
from binnacle.domain.privileged import (
    PRIVILEGED_PROTOCOL_ID,
    PRIVILEGED_PROTOCOL_VERSION,
    BrokerNoAcceptReason,
)
from binnacle.privileged_broker.protocol import (
    PeerCredentials,
    PrivilegedProtocolError,
    acceptance_receipt_to_wire,
    binding_snapshot_to_wire,
    error_response,
    success_response,
)


def _settings() -> PrivilegedClientSettings:
    return PrivilegedClientSettings(
        socket_path=Path("/run/binnacle-privileged/test.sock"),
        expected_peer_uid=0,
        expected_peer_gid=0,
    )


def test_client_settings_reject_unsafe_boundary() -> None:
    with pytest.raises(PrivilegedClientError):
        PrivilegedClientSettings(expected_peer_uid=-1)
    with pytest.raises(PrivilegedClientError):
        PrivilegedClientSettings(connect_timeout_seconds=0.01)
    with pytest.raises(PrivilegedClientError):
        PrivilegedClientSettings(request_timeout_seconds=100.0)
    with pytest.raises(PrivilegedClientError):
        PrivilegedClientSettings(socket_path=Path("relative.sock"))


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
async def test_hello_authenticates_root_peer_correlates_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result: dict[str, object] = {
        "protocol_id": PRIVILEGED_PROTOCOL_ID,
        "protocol_version": PRIVILEGED_PROTOCOL_VERSION,
        "build_sha256": SHA_B,
        "profile_sha256": SHA_C,
        "broker_instance_id": "broker-fixture",
        "broker_generation": 7,
        "backend_ready": False,
        "readiness": "disabled",
    }
    writer, requests, peer_checks = _install_transport(
        monkeypatch,
        lambda request: success_response(request, result),
    )

    hello = await PrivilegedClient(_settings()).hello()

    assert hello.broker_generation == 7
    assert hello.backend_ready is False
    assert requests[0]["type"] == "hello"
    assert str(requests[0]["request_id"]).startswith("req_")
    assert peer_checks == [(0, 0)]
    assert writer.closed is True
    assert writer.waited is True


@pytest.mark.anyio
async def test_exchange_fails_closed_for_server_error_missing_peer_and_wrong_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, _, _ = _install_transport(
        monkeypatch,
        lambda request: error_response(
            str(request["request_id"]),
            str(request["type"]),
            code="privileged_ticket_rejected",
        ),
    )
    with pytest.raises(PrivilegedClientError, match="ticket_rejected"):
        await PrivilegedClient(_settings()).hello()
    assert writer.closed is True

    _install_transport(
        monkeypatch,
        lambda request: {**success_response(request, {}), "type": "get_binding_result"},
    )
    with pytest.raises(PrivilegedClientError, match="response type"):
        await PrivilegedClient(_settings()).hello()

    missing, _, _ = _install_transport(
        monkeypatch,
        lambda request: success_response(request, {}),
        peer_socket=None,
    )
    with pytest.raises(PrivilegedClientError, match="no peer socket"):
        await PrivilegedClient(_settings()).hello()
    assert missing.closed is True

    _install_transport(
        monkeypatch,
        lambda _request: (_ for _ in ()).throw(PrivilegedProtocolError("bad frame")),
    )
    with pytest.raises(PrivilegedClientError, match="failed closed"):
        await PrivilegedClient(_settings()).hello()

    _install_transport(
        monkeypatch,
        lambda request: {
            **error_response(
                str(request["request_id"]),
                str(request["type"]),
                code="failed",
            ),
            "error": {"code": 7},
        },
    )
    with pytest.raises(PrivilegedClientError, match="error code"):
        await PrivilegedClient(_settings()).hello()


class _ResultClient(PrivilegedClient):
    def __init__(self, responses: Mapping[str, object]) -> None:
        super().__init__(_settings())
        self.responses = responses
        self.requests: list[tuple[str, dict[str, object]]] = []

    async def _exchange(self, message_type: str, **fields: object) -> object:
        self.requests.append((message_type, fields))
        return self.responses[message_type]


@pytest.mark.anyio
async def test_hello_and_typed_results_reject_malformed_evidence() -> None:
    valid: dict[str, object] = {
        "protocol_id": PRIVILEGED_PROTOCOL_ID,
        "protocol_version": PRIVILEGED_PROTOCOL_VERSION,
        "build_sha256": SHA_B,
        "profile_sha256": SHA_C,
        "broker_instance_id": "broker-fixture",
        "broker_generation": 1,
        "backend_ready": False,
        "readiness": "disabled",
    }
    for invalid in (
        {**valid, "extra": None},
        {**valid, "broker_generation": True},
        {**valid, "backend_ready": "no"},
        {**valid, "profile_sha256": 7},
    ):
        with pytest.raises(PrivilegedClientError):
            await _ResultClient({"hello": invalid}).hello()

    malformed = acceptance_receipt_to_wire(acceptance_receipt())
    malformed["receipt_sha256"] = "0" * 64
    with pytest.raises(PrivilegedClientError, match="invalid evidence"):
        await _ResultClient({"start_privileged": malformed}).start(privileged_ticket())

    assert await _ResultClient({"get_binding": None}).get("operation:missing") is None


@pytest.mark.anyio
async def test_typed_operations_encode_and_decode_exact_evidence() -> None:
    snapshot = binding_snapshot()
    receipt = acceptance_receipt()
    client = _ResultClient(
        {
            "start_privileged": acceptance_receipt_to_wire(receipt),
            "get_binding": binding_snapshot_to_wire(snapshot),
            "seal_no_accept": acceptance_receipt_to_wire(receipt),
        }
    )

    assert await client.start(privileged_ticket()) == receipt
    message_type, fields = client.requests[0]
    assert message_type == "start_privileged"
    assert isinstance(fields["ticket"], dict)
    assert fields["restart_intent"] is None


@pytest.mark.anyio
async def test_get_and_seal_encode_exact_recovery_identity() -> None:
    snapshot = binding_snapshot()
    receipt = acceptance_receipt()
    client = _ResultClient(
        {
            "get_binding": binding_snapshot_to_wire(snapshot),
            "promote_restart_lkg": binding_snapshot_to_wire(snapshot),
            "seal_no_accept": acceptance_receipt_to_wire(receipt),
        }
    )

    assert await client.get(snapshot.identity.operation_id) == snapshot
    assert (
        await client.promote_restart_lkg(
            snapshot.identity.operation_id,
            audit_closure_evidence_sha256=SHA_C,
            promoted_at=NOW,
        )
        == snapshot
    )
    assert (
        await client.seal_no_accept(
            identity=snapshot.identity,
            reason=BrokerNoAcceptReason.REPLACEMENT_RECOVERY,
            trusted_time_at=NOW,
            retain_until=NOW + timedelta(days=1),
        )
        == receipt
    )
    assert client.requests[0] == (
        "get_binding",
        {"operation_id": snapshot.identity.operation_id},
    )
    assert client.requests[1] == (
        "promote_restart_lkg",
        {
            "operation_id": snapshot.identity.operation_id,
            "audit_closure_evidence_sha256": SHA_C,
            "promoted_at": NOW.isoformat(timespec="microseconds"),
        },
    )
    message_type, fields = client.requests[2]
    assert message_type == "seal_no_accept"
    assert fields["reason"] == "replacement_recovery"
    assert isinstance(fields["identity"], dict)
