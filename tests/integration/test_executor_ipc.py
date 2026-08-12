from __future__ import annotations

import asyncio
import os
import socket
from datetime import timedelta
from pathlib import Path

import pytest
from tests.phase7_support import NOW, SHA_B, SHA_C, execution_ticket, executor_store

from binnacle.adapters.executor_ipc.client import (
    ExecutorClient,
    ExecutorClientError,
    ExecutorClientSettings,
)
from binnacle.domain.execution import (
    CancelDisposition,
    ExecutionStartDisposition,
)
from binnacle.executor.server import (
    ExecutionSupervisorService,
    ExecutorServerIdentity,
    start_executor_server,
)


def test_executor_ipc_is_peer_bound_concurrent_and_fail_closed(tmp_path: Path) -> None:
    async def exercise() -> None:
        socket_path = tmp_path / "supervisor.sock"
        try:
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        except PermissionError:
            pytest.skip("this sandbox denies AF_UNIX socket creation")
        listener.bind(str(socket_path))
        listener.listen(32)
        ticket = execution_ticket()
        async with executor_store(tmp_path / "executor", Path(__file__).parents[2]) as store:
            identity = ExecutorServerIdentity(
                build_sha256=SHA_B,
                profile_sha256=SHA_C,
                supervisor_instance_id="supervisor-fixture",
                supervisor_generation=1,
                expected_client_uid=os.getuid(),
                expected_client_gid=os.getgid(),
                readiness=store.readiness,
            )
            service = ExecutionSupervisorService(store=store, identity=identity)
            server = await start_executor_server(listener, service)
            try:
                client = ExecutorClient(
                    ExecutorClientSettings(
                        socket_path=socket_path,
                        expected_peer_uid=os.getuid(),
                        expected_peer_gid=os.getgid(),
                    )
                )
                hello = await client.hello()
                assert hello.backend_ready is False
                with pytest.raises(ExecutorClientError, match="execution_ticket_rejected"):
                    await client.start(ticket)

                cancel, snapshot = await asyncio.gather(
                    client.cancel(ticket.routing_identity, 3),
                    client.get(ticket.operation_id),
                )
                assert cancel.disposition is CancelDisposition.PENDING_PREACCEPT
                assert snapshot is None
                sealed = await client.seal_no_accept(
                    ticket.routing_identity,
                    "application_runtime_lost",
                    3,
                    NOW + timedelta(hours=1),
                )
                assert sealed.disposition is ExecutionStartDisposition.NO_ACCEPT_PROVEN
            finally:
                server.close()
                await server.wait_closed()

    asyncio.run(exercise())


def test_executor_ipc_test_handler_replays_one_acceptance(tmp_path: Path) -> None:
    async def exercise() -> None:
        socket_path = tmp_path / "supervisor.sock"
        try:
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        except PermissionError:
            pytest.skip("this sandbox denies AF_UNIX socket creation")
        listener.bind(str(socket_path))
        listener.listen(32)
        ticket = execution_ticket()
        async with executor_store(tmp_path / "executor", Path(__file__).parents[2]) as store:
            service = ExecutionSupervisorService(
                store=store,
                identity=ExecutorServerIdentity(
                    build_sha256=SHA_B,
                    profile_sha256=SHA_C,
                    supervisor_instance_id="supervisor-fixture",
                    supervisor_generation=1,
                    expected_client_uid=os.getuid(),
                    expected_client_gid=os.getgid(),
                    readiness=store.readiness,
                ),
                start_handler=store.accept_once,
                ticket_validator=lambda value: value,
            )
            server = await start_executor_server(listener, service)
            try:
                client = ExecutorClient(
                    ExecutorClientSettings(
                        socket_path=socket_path,
                        expected_peer_uid=os.getuid(),
                        expected_peer_gid=os.getgid(),
                    )
                )
                first, replay = await asyncio.gather(client.start(ticket), client.start(ticket))
                assert first == replay
                assert first.disposition is ExecutionStartDisposition.ACCEPTED_EXECUTION
            finally:
                server.close()
                await server.wait_closed()

    asyncio.run(exercise())
