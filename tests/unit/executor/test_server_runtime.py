"""Behavioral tests for the executor protocol server and runtime composition."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from tests.phase7_support import BOOT_SHA, NOW, SHA_A, SHA_B, SHA_C, execution_ticket

from binnacle.domain.execution import (
    CancelDisposition,
    CancelRoutingDisposition,
    CancelRoutingResult,
    CreateReceiptDisposition,
    ExecutionConflictError,
    ExecutionStartDisposition,
    ExecutionStartReceipt,
    ExecutionTicket,
    ExecutorEvidenceEvent,
    ExecutorEvidenceState,
    ExecutorOutputChunk,
    ExecutorSnapshot,
    NoAcceptSealResult,
    OutputAvailability,
    OutputStream,
    TicketRoutingIdentity,
)
from binnacle.executor import runtime as runtime_module
from binnacle.executor import server as server_module
from binnacle.executor.config import ExecutorSettings
from binnacle.executor.protocol import (
    ExecutorProtocolError,
    PeerCredentials,
    cancel_receipt_from_wire,
    read_frame,
    request_envelope,
    validate_response,
)
from binnacle.executor.server import (
    ExecutionSupervisorService,
    ExecutorServerError,
    ExecutorServerIdentity,
    start_executor_server,
)
from binnacle.executor.state import (
    ExecutorStoreIdentity,
    ExecutorStoreSettings,
    SqliteExecutorEvidenceStore,
)
from binnacle.executor.tickets import ExecutionTicketRejected


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


def _start_receipt(snapshot: ExecutorSnapshot) -> ExecutionStartReceipt:
    return ExecutionStartReceipt(
        disposition=ExecutionStartDisposition.ACCEPTED_EXECUTION,
        execution_id=snapshot.execution_id,
        evidence_generation=2,
        accepted_at=NOW,
        executor_reference="executor-reference",
        no_accept_reference=None,
        receipt_sha256=SHA_A,
    )


class _Store:
    def __init__(self) -> None:
        self.snapshot: ExecutorSnapshot | None = _snapshot()
        self.cancel_result = CancelRoutingResult(
            disposition=CancelRoutingDisposition.PENDING_PREACCEPT,
            acknowledged_cancel_generation=1,
            evidence_generation=1,
            snapshot=None,
        )
        self.seal_result = NoAcceptSealResult(
            disposition=ExecutionStartDisposition.NO_ACCEPT_PROVEN,
            acknowledged_cancel_generation=1,
            evidence_generation=2,
            snapshot=None,
            seal_reference="seal-reference",
            executor_reference=None,
            receipt_sha256=SHA_B,
        )
        self.supervisor_generation = 4
        self.readiness = "recovering"
        self.closed = False
        self.cancel_calls: list[tuple[TicketRoutingIdentity, int]] = []
        self.seal_calls: list[tuple[TicketRoutingIdentity, str, int, datetime]] = []
        self.events: list[str] = []

    async def accept_once(self, ticket: ExecutionTicket) -> ExecutionStartReceipt:
        assert self.snapshot is not None
        assert ticket.operation_id == self.snapshot.operation_id
        return _start_receipt(self.snapshot)

    async def cancel_or_attach(
        self,
        *,
        identity: TicketRoutingIdentity,
        cancel_generation: int,
    ) -> CancelRoutingResult:
        self.cancel_calls.append((identity, cancel_generation))
        return self.cancel_result

    async def seal_no_accept(
        self,
        *,
        identity: TicketRoutingIdentity,
        reason: str,
        close_generation: int,
        retain_until: datetime,
    ) -> NoAcceptSealResult:
        self.seal_calls.append((identity, reason, close_generation, retain_until))
        return self.seal_result

    async def get(self, operation_id: str) -> ExecutorSnapshot | None:
        if self.snapshot is None or operation_id != self.snapshot.operation_id:
            return None
        return self.snapshot

    async def list(
        self,
        operation_ids: tuple[str, ...],
    ) -> tuple[ExecutorSnapshot, ...]:
        if self.snapshot is None or self.snapshot.operation_id not in operation_ids:
            return ()
        return (self.snapshot,)

    async def list_outstanding(
        self,
        *,
        after_operation_id: str | None = None,
        limit: int = 256,
    ) -> tuple[ExecutorSnapshot, ...]:
        del after_operation_id, limit
        self.events.append("reconcile")
        return ()

    async def apply_event(self, event: ExecutorEvidenceEvent) -> ExecutorSnapshot:
        del event
        if self.snapshot is None:
            raise AssertionError("fixture has no snapshot")
        return self.snapshot

    async def set_readiness(self, readiness: str) -> None:
        self.events.append(f"readiness:{readiness}")
        self.readiness = readiness

    async def close(self) -> None:
        self.events.append("store:close")
        self.closed = True


def _identity(*, readiness: str = "ready") -> ExecutorServerIdentity:
    return ExecutorServerIdentity(
        build_sha256=SHA_B,
        profile_sha256=SHA_C,
        supervisor_instance_id="supervisor-fixture",
        supervisor_generation=4,
        expected_client_uid=1001,
        expected_client_gid=1002,
        readiness=readiness,
    )


@pytest.mark.anyio
async def test_default_service_reports_readiness_but_keeps_effects_unavailable() -> None:
    store = _Store()
    service = ExecutionSupervisorService(store=store, identity=_identity(readiness="recovering"))

    hello = await service.dispatch(request_envelope("request-hello", "hello"))

    assert isinstance(hello, Mapping)
    assert hello["backend_ready"] is False
    assert hello["readiness"] == "recovering"
    with pytest.raises(ExecutionTicketRejected, match="not promoted"):
        await service.dispatch(
            request_envelope(
                "request-start",
                "start_execution",
                ticket=execution_ticket().to_wire(),
            )
        )
    with pytest.raises(ExecutionTicketRejected, match="output is unavailable"):
        await service.dispatch(
            request_envelope(
                "request-output",
                "read_output",
                operation_id="op-fixture",
                stream="stdout",
                offset=0,
                max_bytes=128,
            )
        )


@pytest.mark.anyio
async def test_test_only_handlers_validate_start_and_bound_output_reads() -> None:
    store = _Store()
    snapshot = _snapshot()
    validated: list[ExecutionTicket] = []
    output_calls: list[tuple[str, OutputStream, int, int]] = []

    def validate_ticket(ticket: ExecutionTicket) -> object:
        validated.append(ticket)
        return object()

    async def start(ticket: ExecutionTicket) -> ExecutionStartReceipt:
        assert ticket == validated[-1]
        return _start_receipt(snapshot)

    async def read_output(
        operation_id: str,
        stream: OutputStream,
        offset: int,
        maximum: int,
    ) -> ExecutorOutputChunk:
        output_calls.append((operation_id, stream, offset, maximum))
        return ExecutorOutputChunk(
            operation_id=operation_id,
            execution_id=snapshot.execution_id,
            stream=stream,
            offset=offset,
            next_offset=offset + 3,
            data=b"log",
            eof=False,
            availability=OutputAvailability.AVAILABLE,
            stream_sha256=None,
        )

    service = ExecutionSupervisorService(
        store=store,
        identity=_identity(),
        start_handler=start,
        ticket_validator=validate_ticket,
        output_reader=read_output,
    )
    ticket = execution_ticket()

    start_result = await service.dispatch(
        request_envelope(
            "request-start",
            "start_execution",
            ticket=ticket.to_wire(),
        )
    )
    output_result = await service.dispatch(
        request_envelope(
            "request-output",
            "read_output",
            operation_id=ticket.operation_id,
            stream="stderr",
            offset=9,
            max_bytes=256,
        )
    )

    assert isinstance(start_result, Mapping)
    assert start_result["execution_id"] == snapshot.execution_id
    assert validated == [ticket]
    assert isinstance(output_result, Mapping)
    assert output_result["next_offset"] == 12
    assert output_calls == [(ticket.operation_id, OutputStream.STDERR, 9, 256)]

    with pytest.raises(ExecutorProtocolError, match="cursor is invalid"):
        await service.dispatch(
            request_envelope(
                "request-output-invalid",
                "read_output",
                operation_id=ticket.operation_id,
                stream="stdout",
                offset=-1,
                max_bytes=1,
            )
        )


@pytest.mark.anyio
async def test_control_dispatch_routes_exact_identity_and_rejects_stale_execution() -> None:
    store = _Store()
    ticket = execution_ticket()
    snapshot = replace(
        _snapshot(),
        effective_cancel_generation=3,
        acknowledged_cancel_generation=3,
        cancel_disposition=CancelDisposition.SIGNAL_PENDING,
    )
    store.snapshot = snapshot
    store.cancel_result = CancelRoutingResult(
        disposition=CancelRoutingDisposition.ACCEPTED_EXECUTION,
        acknowledged_cancel_generation=3,
        evidence_generation=4,
        snapshot=snapshot,
    )
    service = ExecutionSupervisorService(store=store, identity=_identity())

    get_result = await service.dispatch(
        request_envelope(
            "request-get",
            "get_execution",
            operation_id=ticket.operation_id,
        )
    )
    list_result = await service.dispatch(
        request_envelope(
            "request-list",
            "list_executions",
            operation_ids=[ticket.operation_id],
        )
    )
    cancel_result = await service.dispatch(
        request_envelope(
            "request-cancel",
            "request_cancel",
            identity={
                "operation_id": ticket.routing_identity.operation_id,
                "ticket_id": ticket.routing_identity.ticket_id,
                "ticket_sha256": ticket.routing_identity.ticket_sha256,
                "nonce_sha256": ticket.routing_identity.nonce_sha256,
                "boot_id_digest": ticket.routing_identity.boot_id_digest,
                "expires_at": ticket.routing_identity.expires_at.isoformat(),
                "monotonic_deadline_ns": ticket.routing_identity.monotonic_deadline_ns,
            },
            cancel_generation=3,
            execution_id=snapshot.execution_id,
        )
    )
    seal_result = await service.dispatch(
        request_envelope(
            "request-seal",
            "seal_no_accept",
            identity={
                "operation_id": ticket.routing_identity.operation_id,
                "ticket_id": ticket.routing_identity.ticket_id,
                "ticket_sha256": ticket.routing_identity.ticket_sha256,
                "nonce_sha256": ticket.routing_identity.nonce_sha256,
                "boot_id_digest": ticket.routing_identity.boot_id_digest,
                "expires_at": ticket.routing_identity.expires_at.isoformat(),
                "monotonic_deadline_ns": ticket.routing_identity.monotonic_deadline_ns,
            },
            reason="application_runtime_lost",
            close_generation=3,
            retain_until=(NOW + timedelta(hours=1)).isoformat(),
        )
    )

    assert isinstance(get_result, Mapping)
    assert get_result["execution_id"] == snapshot.execution_id
    assert isinstance(list_result, list) and len(list_result) == 1
    receipt = cancel_receipt_from_wire(cancel_result)
    assert receipt.disposition is CancelDisposition.SIGNAL_PENDING
    assert receipt.execution_id == snapshot.execution_id
    assert store.cancel_calls == [(ticket.routing_identity, 3)]
    assert isinstance(seal_result, Mapping)
    assert seal_result["seal_reference"] == "seal-reference"
    assert store.seal_calls[0][0] == ticket.routing_identity

    with pytest.raises(ExecutionConflictError, match="identity is stale"):
        await service.dispatch(
            request_envelope(
                "request-stale-cancel",
                "request_cancel",
                identity={
                    "operation_id": ticket.routing_identity.operation_id,
                    "ticket_id": ticket.routing_identity.ticket_id,
                    "ticket_sha256": ticket.routing_identity.ticket_sha256,
                    "nonce_sha256": ticket.routing_identity.nonce_sha256,
                    "boot_id_digest": ticket.routing_identity.boot_id_digest,
                    "expires_at": ticket.routing_identity.expires_at.isoformat(),
                    "monotonic_deadline_ns": ticket.routing_identity.monotonic_deadline_ns,
                },
                cancel_generation=3,
                execution_id="execution-stale",
            )
        )


def test_service_requires_start_authority_to_be_promoted_atomically() -> None:
    async def start(_ticket: ExecutionTicket) -> ExecutionStartReceipt:
        return _start_receipt(_snapshot())

    with pytest.raises(ExecutorServerError, match="promoted together"):
        ExecutionSupervisorService(
            store=_Store(),
            identity=_identity(),
            start_handler=start,
        )


class _ConnectionWriter:
    def __init__(self) -> None:
        self.closed = 0
        self.waited = 0
        self.peer = cast(socket.socket, object())

    def get_extra_info(self, name: str) -> socket.socket | None:
        assert name == "socket"
        return self.peer

    def close(self) -> None:
        self.closed += 1

    async def wait_closed(self) -> None:
        self.waited += 1


@pytest.mark.anyio
async def test_connection_maps_dispatch_errors_and_always_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ExecutionSupervisorService(store=_Store(), identity=_identity())
    request = request_envelope(
        "request-start",
        "start_execution",
        ticket=execution_ticket().to_wire(),
    )
    responses: list[dict[str, object]] = []
    writer = _ConnectionWriter()

    def trust_peer(
        _sock: socket.socket,
        *,
        expected_uid: int,
        expected_gid: int,
    ) -> PeerCredentials:
        assert (expected_uid, expected_gid) == (1001, 1002)
        return PeerCredentials(pid=1, uid=expected_uid, gid=expected_gid)

    async def provide_request(_reader: asyncio.StreamReader) -> dict[str, object]:
        return request

    async def record_response(
        _writer: asyncio.StreamWriter,
        value: Mapping[str, object],
    ) -> None:
        responses.append(dict(value))

    monkeypatch.setattr(server_module, "require_peer", trust_peer)
    monkeypatch.setattr(server_module, "read_frame", provide_request)
    monkeypatch.setattr(server_module, "write_frame", record_response)

    await service.handle_connection(
        asyncio.StreamReader(),
        cast(asyncio.StreamWriter, writer),
    )

    validate_response(responses[0], request_id="request-start")
    assert responses[0]["ok"] is False
    assert responses[0]["error"] == {"code": "execution_ticket_rejected"}
    assert writer.closed == 1
    assert writer.waited == 1


@pytest.mark.anyio
async def test_connection_swallows_write_failure_but_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ExecutionSupervisorService(store=_Store(), identity=_identity())

    monkeypatch.setattr(
        server_module,
        "require_peer",
        lambda *_args, **_kwargs: PeerCredentials(pid=1, uid=1001, gid=1002),
    )

    async def hello_request(_reader: asyncio.StreamReader) -> dict[str, object]:
        return request_envelope("request-hello", "hello")

    async def fail_write(
        _writer: asyncio.StreamWriter,
        _value: Mapping[str, object],
    ) -> None:
        raise OSError("peer closed")

    monkeypatch.setattr(server_module, "read_frame", hello_request)
    monkeypatch.setattr(server_module, "write_frame", fail_write)
    failed_writer = _ConnectionWriter()
    await service.handle_connection(
        asyncio.StreamReader(),
        cast(asyncio.StreamWriter, failed_writer),
    )
    assert (failed_writer.closed, failed_writer.waited) == (1, 1)

    async def cancel_read(_reader: asyncio.StreamReader) -> dict[str, object]:
        raise asyncio.CancelledError

    monkeypatch.setattr(server_module, "read_frame", cancel_read)
    cancelled_writer = _ConnectionWriter()
    with pytest.raises(asyncio.CancelledError):
        await service.handle_connection(
            asyncio.StreamReader(),
            cast(asyncio.StreamWriter, cancelled_writer),
        )
    assert (cancelled_writer.closed, cancelled_writer.waited) == (1, 1)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "frame, message",
    [
        (b"\x00\x00", "truncated or invalid"),
        ((1).to_bytes(4, "big") + b"{", "length is invalid"),
        (len(b"{]").to_bytes(4, "big") + b"{]", "truncated or invalid"),
        ((2).to_bytes(4, "big") + b"[]", "one JSON object"),
    ],
)
async def test_protocol_rejects_truncated_invalid_and_nonobject_frames(
    frame: bytes,
    message: str,
) -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(frame)
    reader.feed_eof()
    with pytest.raises(ExecutorProtocolError, match=message):
        await read_frame(reader)


def test_server_identity_and_listener_validation_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ExecutorServerError, match="readiness"):
        _identity(readiness="starting")

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(ExecutorServerError, match="Unix stream"):
            asyncio.run(
                start_executor_server(
                    listener,
                    ExecutionSupervisorService(store=_Store(), identity=_identity()),
                )
            )
    finally:
        listener.close()

    monkeypatch.delenv("LISTEN_PID", raising=False)
    monkeypatch.delenv("LISTEN_FDS", raising=False)
    with pytest.raises(ExecutorServerError, match="requires one"):
        server_module.inherited_listener()


class _RuntimeListener:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def close(self) -> None:
        self.events.append("listener:close")


class _RuntimeServer:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def serve_forever(self) -> None:
        self.events.append("server:serve")

    def close(self) -> None:
        self.events.append("server:close")

    async def wait_closed(self) -> None:
        self.events.append("server:wait_closed")


def _runtime_settings() -> ExecutorSettings:
    return ExecutorSettings(
        database_path=Path("/var/lib/binnacle-executor/state/executor-state.sqlite3"),
        runtime_directory=Path("/run/binnacle-executor/private"),
        output_directory=Path("/var/lib/binnacle-executor/output"),
        expected_application_uid=1001,
        expected_application_gid=1002,
        build_sha256=SHA_B,
        profile_sha256=SHA_C,
    )


def _install_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_start: bool,
) -> tuple[_Store, _RuntimeListener, _RuntimeServer, list[str], list[ExecutionSupervisorService]]:
    events: list[str] = []
    store = _Store()
    store.events = events
    listener = _RuntimeListener(events)
    server = _RuntimeServer(events)
    services: list[ExecutionSupervisorService] = []

    async def open_store(
        *,
        settings: ExecutorStoreSettings,
        identity: ExecutorStoreIdentity,
    ) -> SqliteExecutorEvidenceStore:
        assert settings.path == _runtime_settings().database_path
        assert identity.boot_id_digest == BOOT_SHA
        events.append("store:open")
        return cast(SqliteExecutorEvidenceStore, store)

    async def start_server(
        observed_listener: socket.socket,
        service: ExecutionSupervisorService,
    ) -> asyncio.AbstractServer:
        assert observed_listener is cast(socket.socket, listener)
        services.append(service)
        events.append("server:start")
        if fail_start:
            raise RuntimeError("fixture start failed")
        return cast(asyncio.AbstractServer, server)

    monkeypatch.setattr(runtime_module, "load_executor_settings", lambda _path: _runtime_settings())
    monkeypatch.setattr(runtime_module, "boot_id_digest", lambda: BOOT_SHA)
    monkeypatch.setattr(runtime_module, "open_executor_store", open_store)
    monkeypatch.setattr(
        runtime_module,
        "inherited_listener",
        lambda: cast(socket.socket, listener),
    )
    monkeypatch.setattr(runtime_module, "start_executor_server", start_server)
    return store, listener, server, events, services


@pytest.mark.anyio
async def test_runtime_reconciles_before_serving_default_disabled_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, _, events, services = _install_runtime(monkeypatch, fail_start=False)

    await runtime_module.run_executor_service(Path("/etc/binnacle/executor.toml"))

    assert events == [
        "store:open",
        "reconcile",
        "readiness:ready",
        "server:start",
        "server:serve",
        "server:close",
        "server:wait_closed",
        "store:close",
    ]
    assert store.closed is True
    assert len(services) == 1
    hello = await services[0].dispatch(request_envelope("request-runtime", "hello"))
    assert isinstance(hello, Mapping)
    assert hello["backend_ready"] is False
    assert hello["readiness"] == "ready"


@pytest.mark.anyio
async def test_runtime_closes_inherited_listener_when_server_start_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, _, events, _ = _install_runtime(monkeypatch, fail_start=True)

    with pytest.raises(RuntimeError, match="fixture start failed"):
        await runtime_module.run_executor_service(Path("/etc/binnacle/executor.toml"))

    assert events == [
        "store:open",
        "reconcile",
        "readiness:ready",
        "server:start",
        "listener:close",
        "store:close",
    ]
    assert store.closed is True
