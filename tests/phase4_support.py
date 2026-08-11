"""Shared deterministic Phase 4 test builders."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config

from binnacle.adapters.sqlite.engine import (
    DatabaseRuntime,
    DatabaseRuntimeSettings,
    close_database_runtime,
    create_database_runtime,
)
from binnacle.adapters.sqlite.operation_store import SqliteOperationStore
from binnacle.domain.audit import AuditRuntimeIdentity
from binnacle.domain.operation import OperationIntent, OperationOwner


def migrate_database(path: Path, repo_root: Path) -> None:
    config = Config(repo_root / "alembic.ini")
    config.set_main_option("script_location", str(repo_root / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, "head")


@asynccontextmanager
async def operation_runtime(
    root: Path, repo_root: Path
) -> AsyncIterator[tuple[DatabaseRuntime, SqliteOperationStore]]:
    database = root / "state" / "binnacle.db"
    database.parent.mkdir(parents=True)
    migrate_database(database, repo_root)
    settings = DatabaseRuntimeSettings(
        path=database,
        runtime_directory=root / "run",
        verify_runtime_directory=False,
    )
    runtime = await create_database_runtime(settings)
    store = SqliteOperationStore(runtime)
    await store.initialize_kernel(device_id="device-fixture", audit_stream_id="stream-fixture")
    try:
        yield runtime, store
    finally:
        await close_database_runtime(runtime)


def owner(name: str = "controller-fixture") -> OperationOwner:
    return OperationOwner(name, 1, "profile-fixture", "1.0.0")


def intent(*, fingerprint: str = "a" * 64) -> OperationIntent:
    return OperationIntent(
        operation_contract="synthetic.effect",
        operation_contract_version="1.0.0",
        request_fingerprint_sha256=fingerprint,
        device_id="device-fixture",
        device_epoch=1,
        runtime_build_sha256="b" * 64,
        runtime_config_sha256="c" * 64,
        tool_name="internal.synthetic",
        tool_contract_version="1.0.0",
        target_identity_sha256="d" * 64,
        maximum_effect_sha256="e" * 64,
    )


def audit_identity() -> AuditRuntimeIdentity:
    return AuditRuntimeIdentity(
        stream_id="stream-fixture",
        audit_epoch="epoch-1",
        segment_id="segment-1",
        boot_id="boot-fixture",
        device_id="device-fixture",
        server_build_sha256="1" * 64,
        tool_manifest_sha256="2" * 64,
        schema_registry_sha256="3" * 64,
        device_profile_version="1.0.0",
        policy_version="1.0.0",
        redaction_policy_version="1.0.0",
    )


def audit_schema(repo_root: Path) -> dict[str, object]:
    value = json.loads((repo_root / "schemas/audit/audit-event.schema.json").read_text())
    assert isinstance(value, dict)
    return value


NOW = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
