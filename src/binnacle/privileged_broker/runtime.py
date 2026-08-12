"""Fail-closed composition for the separately installed privileged broker."""

from __future__ import annotations

import asyncio
import os
import secrets
from pathlib import Path

from binnacle.domain.privileged import PRIVILEGED_PROTOCOL_VERSION, PrivilegedTicket
from binnacle.privileged_broker.artifact import verify_privileged_artifact
from binnacle.privileged_broker.config import boot_id_sha256, load_privileged_broker_settings
from binnacle.privileged_broker.server import (
    PrivilegedBrokerService,
    PrivilegedServerIdentity,
    inherited_listener,
    start_privileged_server,
)
from binnacle.privileged_broker.state import (
    PrivilegedStoreIdentity,
    PrivilegedStoreSettings,
    open_privileged_store,
)
from binnacle.privileged_broker.tickets import PrivilegedTicketRejected


class _UnavailableTicketVerifier:
    """Prevent ticket promotion until a reviewed integrity mechanism is installed."""

    def validate(self, ticket: PrivilegedTicket) -> None:
        del ticket
        raise PrivilegedTicketRejected("privileged ticket verification is not promoted")


async def run_privileged_broker_service(config_path: Path) -> None:
    """Serve retained evidence while every new privileged effect remains unavailable."""

    if os.geteuid() != 0 or os.getegid() != 0:
        raise RuntimeError("privileged broker requires the dedicated root service identity")
    settings = load_privileged_broker_settings(config_path)
    verify_privileged_artifact(expected_build_sha256=settings.build_sha256)
    broker_instance_id = f"broker_{secrets.token_hex(16)}"
    store = await open_privileged_store(
        settings=PrivilegedStoreSettings(
            path=settings.database_path,
            runtime_directory=settings.runtime_directory,
            busy_timeout_ms=settings.busy_timeout_ms,
            runtime_group_gid=settings.runtime_group_gid,
        ),
        identity=PrivilegedStoreIdentity(
            broker_instance_id=broker_instance_id,
            boot_id_sha256=boot_id_sha256(),
            protocol_version=PRIVILEGED_PROTOCOL_VERSION,
            build_sha256=settings.build_sha256,
            profile_sha256=settings.profile_sha256,
        ),
        ticket_verifier=_UnavailableTicketVerifier(),
        acceptance_enabled=settings.acceptance_enabled,
    )
    listener = None
    server: asyncio.AbstractServer | None = None
    try:
        listener = inherited_listener()
        service = PrivilegedBrokerService(
            store=store,
            identity=PrivilegedServerIdentity(
                build_sha256=settings.build_sha256,
                profile_sha256=settings.profile_sha256,
                broker_instance_id=broker_instance_id,
                broker_generation=store.broker_generation,
                expected_client_uid=settings.expected_application_uid,
                expected_client_gid=settings.expected_application_gid,
                readiness=store.readiness,
            ),
            start_handler=None,
        )
        server = await start_privileged_server(listener, service)
        await server.serve_forever()
    finally:
        if server is not None:
            server.close()
            await server.wait_closed()
        elif listener is not None:
            listener.close()
        await store.close()


__all__ = ["run_privileged_broker_service"]
