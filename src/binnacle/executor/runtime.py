"""Fail-closed production composition for the default-disabled executor service."""

from __future__ import annotations

import asyncio
import secrets
from pathlib import Path

from binnacle.domain.execution import EXECUTOR_PROTOCOL_VERSION
from binnacle.executor.config import boot_id_digest, load_executor_settings
from binnacle.executor.reconcile import ExecutorRestartReconciler
from binnacle.executor.server import (
    ExecutionSupervisorService,
    ExecutorServerIdentity,
    inherited_listener,
    start_executor_server,
)
from binnacle.executor.state import (
    ExecutorStoreIdentity,
    ExecutorStoreSettings,
    open_executor_store,
)


async def run_executor_service(config_path: Path) -> None:
    settings = load_executor_settings(config_path)
    supervisor_instance_id = f"supervisor_{secrets.token_hex(16)}"
    store = await open_executor_store(
        settings=ExecutorStoreSettings(
            path=settings.database_path,
            runtime_directory=settings.runtime_directory,
            busy_timeout_ms=settings.busy_timeout_ms,
        ),
        identity=ExecutorStoreIdentity(
            supervisor_instance_id=supervisor_instance_id,
            boot_id_digest=boot_id_digest(),
            protocol_version=EXECUTOR_PROTOCOL_VERSION,
            build_sha256=settings.build_sha256,
            profile_sha256=settings.profile_sha256,
        ),
    )
    listener = None
    server: asyncio.AbstractServer | None = None
    try:
        await ExecutorRestartReconciler(store).reconcile()
        listener = inherited_listener()
        service = ExecutionSupervisorService(
            store=store,
            identity=ExecutorServerIdentity(
                build_sha256=settings.build_sha256,
                profile_sha256=settings.profile_sha256,
                supervisor_instance_id=supervisor_instance_id,
                supervisor_generation=store.supervisor_generation,
                expected_client_uid=settings.expected_application_uid,
                expected_client_gid=settings.expected_application_gid,
                readiness=store.readiness,
            ),
        )
        server = await start_executor_server(listener, service)
        await server.serve_forever()
    finally:
        if server is not None:
            server.close()
            await server.wait_closed()
        else:
            if listener is not None:
                listener.close()
        await store.close()


__all__ = ["run_executor_service"]
