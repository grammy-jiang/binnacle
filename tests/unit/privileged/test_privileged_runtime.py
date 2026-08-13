"""Composition and cleanup tests for the root broker runtime."""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from binnacle.domain.privileged import PrivilegedTicket
from binnacle.ports.privileged import PrivilegedTicketVerifier
from binnacle.privileged_broker import runtime as runtime_module
from binnacle.privileged_broker.config import PrivilegedBrokerSettings
from binnacle.privileged_broker.protocol import request_envelope
from binnacle.privileged_broker.server import PrivilegedBrokerService
from binnacle.privileged_broker.state import (
    PrivilegedStoreIdentity,
    PrivilegedStoreSettings,
    SqlitePrivilegedEvidenceStore,
)
from binnacle.privileged_broker.tickets import PrivilegedTicketRejected

BOOT_SHA = "c" * 64


def _runtime_settings() -> PrivilegedBrokerSettings:
    return PrivilegedBrokerSettings(
        database_path=Path("/var/lib/binnacle-privileged/evidence.db"),
        runtime_directory=Path("/run/binnacle-privileged"),
        runtime_group_gid=1250,
        expected_application_uid=1200,
        expected_application_gid=1200,
        build_sha256="a" * 64,
        profile_sha256="b" * 64,
        acceptance_enabled=False,
        busy_timeout_ms=5000,
    )


class _Store:
    broker_generation = 7
    readiness = "disabled"

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.closed = False

    async def close(self) -> None:
        self.events.append("store:close")
        self.closed = True


class _Listener:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def close(self) -> None:
        self.events.append("listener:close")


class _Server:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def serve_forever(self) -> None:
        self.events.append("server:serve")

    def close(self) -> None:
        self.events.append("server:close")

    async def wait_closed(self) -> None:
        self.events.append("server:wait_closed")


def _install_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_start: bool,
) -> tuple[_Store, list[str], list[PrivilegedBrokerService]]:
    events: list[str] = []
    store = _Store(events)
    listener = _Listener(events)
    server = _Server(events)
    services: list[PrivilegedBrokerService] = []

    async def open_store(
        *,
        settings: PrivilegedStoreSettings,
        identity: PrivilegedStoreIdentity,
        ticket_verifier: PrivilegedTicketVerifier,
        acceptance_enabled: bool,
    ) -> SqlitePrivilegedEvidenceStore:
        assert settings.runtime_group_gid == 1250
        assert identity.boot_id_sha256 == BOOT_SHA
        assert acceptance_enabled is False
        with pytest.raises(PrivilegedTicketRejected, match="not promoted"):
            ticket_verifier.validate(cast(PrivilegedTicket, object()))
        events.append("store:open")
        return cast(SqlitePrivilegedEvidenceStore, store)

    def verify_artifact(*, expected_build_sha256: str) -> None:
        assert expected_build_sha256 == "a" * 64
        events.append("artifact:verify")

    async def start_server(
        observed_listener: socket.socket,
        service: PrivilegedBrokerService,
    ) -> asyncio.AbstractServer:
        assert observed_listener is cast(socket.socket, listener)
        services.append(service)
        events.append("server:start")
        if fail_start:
            raise RuntimeError("fixture start failed")
        return cast(asyncio.AbstractServer, server)

    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "getegid", lambda: 0)
    monkeypatch.setattr(
        runtime_module,
        "load_privileged_broker_settings",
        lambda _path: _runtime_settings(),
    )
    monkeypatch.setattr(runtime_module, "boot_id_sha256", lambda: BOOT_SHA)
    monkeypatch.setattr(runtime_module, "verify_privileged_artifact", verify_artifact)
    monkeypatch.setattr(runtime_module, "open_privileged_store", open_store)
    monkeypatch.setattr(
        runtime_module,
        "inherited_listener",
        lambda: cast(socket.socket, listener),
    )
    monkeypatch.setattr(runtime_module, "start_privileged_server", start_server)
    return store, events, services


@pytest.mark.anyio
async def test_runtime_serves_recovery_boundary_with_effect_start_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, events, services = _install_runtime(monkeypatch, fail_start=False)

    await runtime_module.run_privileged_broker_service(Path("/etc/binnacle-privileged/broker.toml"))

    assert events == [
        "artifact:verify",
        "store:open",
        "server:start",
        "server:serve",
        "server:close",
        "server:wait_closed",
        "store:close",
    ]
    assert store.closed is True
    hello = await services[0].dispatch(request_envelope("request-runtime", "hello"))
    assert isinstance(hello, Mapping)
    assert hello["backend_ready"] is False
    assert hello["readiness"] == "disabled"


@pytest.mark.anyio
async def test_runtime_closes_listener_and_store_when_server_start_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, events, _ = _install_runtime(monkeypatch, fail_start=True)

    with pytest.raises(RuntimeError, match="fixture start failed"):
        await runtime_module.run_privileged_broker_service(
            Path("/etc/binnacle-privileged/broker.toml")
        )

    assert events == [
        "artifact:verify",
        "store:open",
        "server:start",
        "listener:close",
        "store:close",
    ]
    assert store.closed is True


@pytest.mark.anyio
async def test_runtime_rejects_nonroot_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    monkeypatch.setattr(os, "getegid", lambda: 1000)

    with pytest.raises(RuntimeError, match="root service identity"):
        await runtime_module.run_privileged_broker_service(
            Path("/etc/binnacle-privileged/broker.toml")
        )
