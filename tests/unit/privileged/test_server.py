"""Default-disabled privileged broker server tests."""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Mapping
from datetime import datetime, timedelta
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

from binnacle.domain.privileged import (
    BrokerAcceptanceReceipt,
    BrokerBindingSnapshot,
    BrokerNoAcceptReason,
    PrivilegedTicket,
    PrivilegedTicketRoutingIdentity,
)
from binnacle.privileged_broker import server as server_module
from binnacle.privileged_broker.protocol import (
    PeerCredentials,
    PrivilegedProtocolError,
    acceptance_receipt_from_wire,
    binding_snapshot_from_wire,
    request_envelope,
    routing_identity_to_wire,
)
from binnacle.privileged_broker.server import (
    PrivilegedBrokerService,
    PrivilegedServerError,
    PrivilegedServerIdentity,
    inherited_listener,
    start_privileged_server,
)
from binnacle.privileged_broker.tickets import PrivilegedTicketRejected


class _Store:
    def __init__(self) -> None:
        self.snapshot: BrokerBindingSnapshot | None = binding_snapshot()
        self.receipt = acceptance_receipt()
        self.seal_calls: list[tuple[BrokerNoAcceptReason, datetime, datetime]] = []
        self.closed = False

    async def accept_once(self, ticket: PrivilegedTicket) -> BrokerAcceptanceReceipt:
        assert ticket.operation_id == self.receipt.operation_id
        return self.receipt

    async def seal_no_accept(
        self,
        *,
        identity: PrivilegedTicketRoutingIdentity,
        reason: BrokerNoAcceptReason,
        trusted_time_at: datetime,
        retain_until: datetime,
    ) -> BrokerAcceptanceReceipt:
        assert identity == privileged_ticket().routing_identity
        self.seal_calls.append((reason, trusted_time_at, retain_until))
        return self.receipt

    async def get(self, operation_id: str) -> BrokerBindingSnapshot | None:
        if self.snapshot is None or operation_id != self.snapshot.identity.operation_id:
            return None
        return self.snapshot

    async def close(self) -> None:
        self.closed = True


def _identity(*, readiness: str = "disabled") -> PrivilegedServerIdentity:
    return PrivilegedServerIdentity(
        build_sha256=SHA_B,
        profile_sha256=SHA_C,
        broker_instance_id="broker-fixture",
        broker_generation=4,
        expected_client_uid=1001,
        expected_client_gid=1002,
        readiness=readiness,
    )


@pytest.mark.anyio
async def test_default_service_reports_identity_and_rejects_new_effects() -> None:
    store = _Store()
    service = PrivilegedBrokerService(store=store, identity=_identity())

    hello = await service.dispatch(request_envelope("request-hello", "hello"))

    assert isinstance(hello, Mapping)
    assert hello["backend_ready"] is False
    assert hello["readiness"] == "disabled"
    with pytest.raises(PrivilegedTicketRejected, match="not promoted"):
        await service.dispatch(
            request_envelope(
                "request-start",
                "start_privileged",
                ticket=privileged_ticket().to_wire(),
                restart_intent=None,
            )
        )


@pytest.mark.anyio
async def test_recovery_get_and_seal_remain_available_without_backend() -> None:
    store = _Store()
    service = PrivilegedBrokerService(store=store, identity=_identity())
    ticket = privileged_ticket()

    get_result = await service.dispatch(
        request_envelope(
            "request-get",
            "get_binding",
            operation_id=ticket.operation_id,
        )
    )
    seal_result = await service.dispatch(
        request_envelope(
            "request-seal",
            "seal_no_accept",
            identity=routing_identity_to_wire(ticket.routing_identity),
            reason="replacement_recovery",
            trusted_time_at=NOW.isoformat(timespec="microseconds"),
            retain_until=(NOW + timedelta(days=1)).isoformat(timespec="microseconds"),
        )
    )

    assert binding_snapshot_from_wire(get_result) == store.snapshot
    assert acceptance_receipt_from_wire(seal_result) == store.receipt
    assert store.seal_calls == [
        (BrokerNoAcceptReason.REPLACEMENT_RECOVERY, NOW, NOW + timedelta(days=1))
    ]

    assert (
        await service.dispatch(
            request_envelope(
                "request-missing",
                "get_binding",
                operation_id="operation:missing",
            )
        )
        is None
    )


@pytest.mark.anyio
async def test_explicit_test_handler_can_accept_exact_ticket() -> None:
    store = _Store()
    accepted: list[PrivilegedTicket] = []

    async def start(
        ticket: PrivilegedTicket, restart_intent: object | None
    ) -> BrokerAcceptanceReceipt:
        assert restart_intent is None
        accepted.append(ticket)
        return await store.accept_once(ticket)

    service = PrivilegedBrokerService(
        store=store,
        identity=_identity(readiness="ready"),
        start_handler=start,
    )
    result = await service.dispatch(
        request_envelope(
            "request-start",
            "start_privileged",
            ticket=privileged_ticket().to_wire(),
            restart_intent=None,
        )
    )

    assert acceptance_receipt_from_wire(result) == store.receipt
    assert accepted == [privileged_ticket()]

    with pytest.raises(PrivilegedProtocolError, match="one object"):
        await service.dispatch(
            {
                "type": "start_privileged",
                "ticket": "not-an-object",
                "restart_intent": None,
            }
        )


@pytest.mark.anyio
async def test_dispatch_rejects_bad_operation_seal_reason_and_time() -> None:
    service = PrivilegedBrokerService(store=_Store(), identity=_identity())
    with pytest.raises(PrivilegedProtocolError, match="operation identity"):
        await service.dispatch({"type": "get_binding", "operation_id": "bad operation"})
    request = request_envelope(
        "request-seal",
        "seal_no_accept",
        identity=routing_identity_to_wire(privileged_ticket().routing_identity),
        reason="unknown",
        trusted_time_at=NOW.isoformat(),
        retain_until=(NOW + timedelta(days=1)).isoformat(),
    )
    with pytest.raises(PrivilegedProtocolError, match="seal reason"):
        await service.dispatch(request)

    request["reason"] = "replacement_recovery"
    request["trusted_time_at"] = "not-a-time"
    with pytest.raises(PrivilegedProtocolError):
        await service.dispatch(request)


class _Writer:
    def __init__(self) -> None:
        self.closed = False
        self.waited = False

    def get_extra_info(self, name: str) -> object:
        assert name == "socket"
        return object()

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        self.waited = True


@pytest.mark.anyio
async def test_connection_checks_exact_peer_and_writes_sanitized_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store()
    service = PrivilegedBrokerService(store=store, identity=_identity())
    writer = _Writer()
    peer_checks: list[tuple[int, int]] = []
    responses: list[dict[str, object]] = []

    def require_test_peer(
        _sock: socket.socket,
        *,
        expected_uid: int,
        expected_gid: int,
    ) -> PeerCredentials:
        peer_checks.append((expected_uid, expected_gid))
        return PeerCredentials(pid=10, uid=expected_uid, gid=expected_gid)

    async def provide_request(_reader: asyncio.StreamReader) -> dict[str, object]:
        return request_envelope("request-hello", "hello")

    async def record_response(
        _writer: asyncio.StreamWriter,
        response: Mapping[str, object],
    ) -> None:
        responses.append(dict(response))

    monkeypatch.setattr(server_module, "require_peer", require_test_peer)
    monkeypatch.setattr(server_module, "read_frame", provide_request)
    monkeypatch.setattr(server_module, "write_frame", record_response)

    await service.handle_connection(
        asyncio.StreamReader(),
        cast(asyncio.StreamWriter, writer),
    )

    assert peer_checks == [(1001, 1002)]
    assert responses[0]["ok"] is True
    assert writer.closed and writer.waited


@pytest.mark.anyio
async def test_connection_sanitizes_rejection_and_missing_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = PrivilegedBrokerService(store=_Store(), identity=_identity())
    responses: list[dict[str, object]] = []

    async def rejected_request(_reader: asyncio.StreamReader) -> dict[str, object]:
        return request_envelope(
            "request-start",
            "start_privileged",
            ticket=privileged_ticket().to_wire(),
            restart_intent=None,
        )

    async def record_response(
        _writer: asyncio.StreamWriter,
        response: Mapping[str, object],
    ) -> None:
        responses.append(dict(response))

    monkeypatch.setattr(
        server_module,
        "require_peer",
        lambda *_args, **_kwargs: PeerCredentials(pid=1, uid=1001, gid=1002),
    )
    monkeypatch.setattr(server_module, "read_frame", rejected_request)
    monkeypatch.setattr(server_module, "write_frame", record_response)
    writer = _Writer()
    await service.handle_connection(asyncio.StreamReader(), cast(asyncio.StreamWriter, writer))
    assert responses[-1]["error"] == {"code": "privileged_ticket_rejected"}

    class _MissingPeerWriter(_Writer):
        def get_extra_info(self, name: str) -> None:
            assert name == "socket"
            return None

    missing = _MissingPeerWriter()
    await service.handle_connection(asyncio.StreamReader(), cast(asyncio.StreamWriter, missing))
    assert responses[-1]["error"] == {"code": "privileged_request_invalid"}


@pytest.mark.anyio
async def test_listener_rejects_non_unix_socket() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(PrivilegedServerError, match="Unix"):
            await start_privileged_server(
                listener,
                PrivilegedBrokerService(store=_Store(), identity=_identity()),
            )
    finally:
        listener.close()


@pytest.mark.anyio
async def test_unix_listener_is_forwarded_without_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    observed: list[socket.socket] = []
    marker = cast(asyncio.AbstractServer, object())

    async def start_server(
        _handler: object,
        *,
        sock: socket.socket,
    ) -> asyncio.AbstractServer:
        observed.append(sock)
        return marker

    monkeypatch.setattr(asyncio, "start_unix_server", start_server)
    try:
        result = await start_privileged_server(
            first,
            PrivilegedBrokerService(store=_Store(), identity=_identity()),
        )
        assert result is marker
        assert observed == [first]
        assert first.getblocking() is False
    finally:
        first.close()
        second.close()


def test_server_identity_and_unknown_dispatch_fail_closed() -> None:
    with pytest.raises(PrivilegedServerError, match="digest"):
        PrivilegedServerIdentity(
            build_sha256="bad",
            profile_sha256=SHA_C,
            broker_instance_id="broker-fixture",
            broker_generation=1,
            expected_client_uid=1,
            expected_client_gid=1,
            readiness="disabled",
        )
    with pytest.raises(PrivilegedServerError):
        _identity(readiness="pretend-ready")
    with pytest.raises(PrivilegedProtocolError):
        request_envelope("request", "unknown")


def test_inherited_listener_fails_closed_without_exact_systemd_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LISTEN_PID", raising=False)
    monkeypatch.delenv("LISTEN_FDS", raising=False)
    with pytest.raises(PrivilegedServerError, match="requires"):
        inherited_listener()
    monkeypatch.setenv("LISTEN_PID", str(os.getpid()))
    monkeypatch.setenv("LISTEN_FDS", "2")
    with pytest.raises(PrivilegedServerError, match="identity"):
        inherited_listener()
