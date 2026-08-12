"""Deterministic Phase 7 execution fixtures."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config

from binnacle.domain.execution import ExecutionTicket, ResourcePlan, build_execution_ticket
from binnacle.executor.state import (
    ExecutorStoreIdentity,
    ExecutorStoreSettings,
    SqliteExecutorEvidenceStore,
    open_executor_store,
)

NOW = datetime.now(UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
BOOT_SHA = "1" * 64


def resource_plan() -> ResourcePlan:
    return ResourcePlan(
        wall_time_seconds=30,
        cpu_time_seconds=20,
        memory_bytes=64 * 1024 * 1024,
        swap_bytes=0,
        pids=16,
        open_files=64,
        output_bytes=1024 * 1024,
        workspace_write_bytes=1024 * 1024,
        workspace_inodes=64,
    )


def execution_ticket(
    *,
    operation_id: str = "op-fixture",
    ticket_id: str = "ticket-fixture",
    nonce: str = "nonce-fixture",
    executable_path: str = "/usr/bin/python3",
    executable_identity_sha256: str = SHA_A,
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
    monotonic_deadline_ns: int | None = None,
    environment: Mapping[object, object] | None = None,
    network_plan_sha256: str = SHA_A,
) -> ExecutionTicket:
    issued = issued_at or NOW
    return build_execution_ticket(
        ticket_id=ticket_id,
        operation_id=operation_id,
        controller_identity_sha256=SHA_A,
        controller_epoch=1,
        device_id="device-fixture",
        device_epoch=1,
        development_session_id="session-fixture",
        development_session_state_version=3,
        development_session_closure_sha256=SHA_B,
        command_profile_id="command-profile-v1",
        workspace_id="workspace-fixture",
        workspace_profile_sha256=SHA_C,
        workspace_root_identity_sha256=SHA_D,
        workspace_mount_identity_sha256=SHA_E,
        workspace_fence_version=7,
        executable_path=executable_path,
        executable_identity_sha256=executable_identity_sha256,
        argv=("python3", "-c", "print('fixture')"),
        cwd_relative=".",
        environment={"LANG": "C.UTF-8"} if environment is None else environment,
        inline_stdin=b"fixture-input",
        stdin_reference_sha256=None,
        workspace_script_sha256=None,
        policy_sha256=SHA_B,
        resource_plan=resource_plan(),
        mount_plan_id="mount-plan-v1",
        mount_plan_sha256=SHA_C,
        sandbox_profile_id="sandbox-profile-v1",
        sandbox_plan_sha256=SHA_D,
        process_isolation_profile_id="process-profile-v1",
        process_isolation_plan_sha256=SHA_E,
        network_profile_id="network-denied-v1",
        network_plan_sha256=network_plan_sha256,
        listener_exposure="denied",
        admission_record_id="decision-fixture",
        issued_at=issued,
        expires_at=expires_at or issued + timedelta(minutes=10),
        boot_id_digest=BOOT_SHA,
        monotonic_deadline_ns=(
            monotonic_deadline_ns
            if monotonic_deadline_ns is not None
            else time.monotonic_ns() + 600_000_000_000
        ),
        single_use_nonce=nonce,
    )


def migrate_executor_database(path: Path, repo_root: Path) -> None:
    config = Config(repo_root / "alembic-executor.ini")
    config.set_main_option("script_location", str(repo_root / "migrations_executor"))
    config.attributes["database_url"] = f"sqlite:///{path}"
    command.upgrade(config, "head")


@asynccontextmanager
async def executor_store(
    root: Path,
    repo_root: Path,
    *,
    migrate: bool = True,
) -> AsyncIterator[SqliteExecutorEvidenceStore]:
    state = root / "state"
    runtime = root / "run"
    state.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    database = state / "executor-state.sqlite3"
    if migrate:
        migrate_executor_database(database, repo_root)
    store = await open_executor_store(
        settings=ExecutorStoreSettings(
            path=database,
            runtime_directory=runtime,
            verify_permissions=False,
        ),
        identity=ExecutorStoreIdentity(
            supervisor_instance_id="supervisor-fixture",
            boot_id_digest=BOOT_SHA,
            protocol_version="1.0",
            build_sha256=SHA_B,
            profile_sha256=SHA_C,
        ),
    )
    try:
        yield store
    finally:
        await store.close()
