"""Fresh migration, schema constraints, pragmas, and runtime-lock tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from tests.phase4_support import migrate_database

from binnacle.adapters.sqlite.engine import (
    DatabaseRuntimeError,
    DatabaseRuntimeSettings,
    close_database_runtime,
    create_database_runtime,
    verify_database_runtime,
    verify_runtime_directory,
)
from binnacle.adapters.sqlite.migrations import current_revision, upgrade_database

EXPECTED_COLUMNS = {
    "kernel_meta": {
        "id",
        "schema_generation",
        "device_id",
        "device_epoch",
        "created_at",
        "updated_at",
        "audit_stream_id",
        "audit_epoch",
        "audit_epoch_generation",
        "audit_last_sequence",
        "audit_last_hash",
        "audit_failure_generation",
        "audit_failure_latched",
        "audit_failure_reason_code",
        "audit_failure_detected_at",
        "audit_recovered_generation",
        "audit_recovery_evidence_sha256",
        "trusted_wall_time_high_watermark",
        "trusted_time_boot_id_digest",
        "trusted_time_monotonic_ns",
        "trusted_time_generation",
        "consequential_admission_enabled",
    },
    "controller_owners": {
        "controller_id",
        "controller_epoch",
        "controller_profile_id",
        "controller_profile_version",
        "first_seen_at",
        "last_seen_at",
        "active",
    },
    "operations": {
        "operation_id",
        "controller_id",
        "controller_epoch",
        "device_id",
        "device_epoch",
        "operation_contract",
        "operation_contract_version",
        "tool_name",
        "tool_contract_version",
        "request_fingerprint_sha256",
        "state",
        "state_version",
        "effect_knowledge",
        "terminality",
        "automatic_retry_allowed",
        "effect_boundary_crossed_at",
        "effect_reference",
        "effect_reference_digest",
        "error_code",
        "error_summary",
        "retry_action",
        "runtime_build_sha256",
        "runtime_config_sha256",
        "controller_profile_version_snapshot",
        "created_at",
        "updated_at",
        "authorised_at",
        "started_at",
        "terminal_at",
        "last_reconciled_at",
    },
    "operation_transitions": {
        "operation_id",
        "state_version",
        "from_state",
        "to_state",
        "effect_knowledge",
        "terminality",
        "reason_code",
        "error_code",
        "recorded_at",
        "runtime_build_sha256",
    },
    "idempotency_bindings": {
        "binding_id",
        "device_id",
        "device_epoch",
        "key_mode",
        "key_digest_sha256",
        "tool_name",
        "contract_version",
        "owner_controller_id",
        "owner_controller_epoch",
        "owner_controller_digest",
        "request_fingerprint_sha256",
        "prepared_operation_id",
        "prepared_input_sha256",
        "prepared_expires_at",
        "prepared_state_binding_sha256",
        "prepared_registered_boot_id_digest",
        "prepared_monotonic_deadline_ns",
        "target_identity_sha256",
        "maximum_effect_sha256",
        "operation_id",
        "terminal_class",
        "created_at",
        "last_access_at",
        "terminal_at",
        "retired_at",
        "record_kind",
        "duplicate_count",
        "conflict_count",
    },
    "policy_decisions": {
        "policy_decision_id",
        "operation_id",
        "policy_id",
        "policy_version",
        "decision",
        "controller_id",
        "controller_epoch",
        "operation_contract",
        "operation_contract_version",
        "required_scope_digest",
        "normalized_target_digest",
        "input_facts_sha256",
        "reason_codes_json",
        "decided_at",
        "runtime_policy_sha256",
    },
    "payload_objects": {
        "payload_id",
        "operation_id",
        "controller_id",
        "controller_epoch",
        "kind",
        "lifecycle",
        "relative_path",
        "media_type",
        "encoding",
        "decoded_byte_count",
        "sha256",
        "truncated",
        "information_class",
        "retention_class",
        "created_at",
        "completed_at",
        "expires_at",
        "last_access_at",
    },
    "operation_evidence": {
        "evidence_id",
        "operation_id",
        "source",
        "provenance",
        "information_class",
        "fresh_until",
        "result_sha256",
        "payload_id",
        "audit_ref",
        "facts_json",
        "recorded_at",
    },
}


@pytest.mark.anyio
async def test_fresh_upgrade_has_exact_authoritative_shape_and_pragmas(
    tmp_path: Path, repo_root: Path
) -> None:
    database = tmp_path / "state/binnacle.db"
    database.parent.mkdir()
    migrate_database(database, repo_root)
    runtime = await create_database_runtime(
        DatabaseRuntimeSettings(database, tmp_path / "run", verify_runtime_directory=False)
    )
    try:
        health = await verify_database_runtime(runtime)
        assert health.healthy
        assert health.revision == "0001_durable_operation_kernel"
        assert health.foreign_keys == 1
        assert health.journal_mode == "wal"
        assert health.synchronous == 2
        async with runtime.engine.connect() as connection:
            tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
            columns = await connection.run_sync(
                lambda sync: {
                    table: {item["name"] for item in inspect(sync).get_columns(table)}
                    for table in EXPECTED_COLUMNS
                }
            )
            policy_fks = await connection.run_sync(
                lambda sync: inspect(sync).get_foreign_keys("policy_decisions")
            )
            policy_unique = await connection.run_sync(
                lambda sync: inspect(sync).get_unique_constraints("policy_decisions")
            )
            binding_checks = await connection.run_sync(
                lambda sync: {
                    item["name"]
                    for item in inspect(sync).get_check_constraints("idempotency_bindings")
                }
            )
            kernel_checks = await connection.run_sync(
                lambda sync: {
                    item["name"] for item in inspect(sync).get_check_constraints("kernel_meta")
                }
            )
            indexes = await connection.run_sync(
                lambda sync: {
                    table: {item["name"] for item in inspect(sync).get_indexes(table)}
                    for table in ("operations", "idempotency_bindings", "payload_objects")
                }
            )
        assert tables == set(EXPECTED_COLUMNS) | {"alembic_version"}
        assert columns == EXPECTED_COLUMNS
        assert {tuple(item["constrained_columns"]) for item in policy_fks} == {("operation_id",)}
        assert ("operation_id",) in {tuple(item["column_names"]) for item in policy_unique}
        assert "ck_bindings_owner_shape" in binding_checks
        assert "ck_kernel_meta_time_monotonic" in kernel_checks
        assert "ck_kernel_meta_admission_safe" in kernel_checks
        assert indexes == {
            "operations": {"ix_operations_state"},
            "idempotency_bindings": {"ix_bindings_operation"},
            "payload_objects": {"ix_payload_owner"},
        }
    finally:
        await close_database_runtime(runtime)


@pytest.mark.anyio
async def test_live_writer_lock_and_revision_mismatch_fail_closed(
    tmp_path: Path, repo_root: Path
) -> None:
    database = tmp_path / "state/binnacle.db"
    database.parent.mkdir()
    migrate_database(database, repo_root)
    settings = DatabaseRuntimeSettings(database, tmp_path / "run", verify_runtime_directory=False)
    runtime = await create_database_runtime(settings)
    try:
        with pytest.raises(DatabaseRuntimeError, match="already active"):
            await create_database_runtime(settings)
        async with runtime.engine.begin() as connection:
            await connection.execute(
                text("UPDATE alembic_version SET version_num='unexpected_revision'")
            )
        assert not (await verify_database_runtime(runtime)).healthy
    finally:
        await close_database_runtime(runtime)


def test_migration_refuses_unmanaged_tables(tmp_path: Path, repo_root: Path) -> None:
    database = tmp_path / "unmanaged.db"
    import sqlite3

    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()
    with pytest.raises(RuntimeError, match="unmanaged"):
        migrate_database(database, repo_root)


def test_bare_alembic_invocation_requires_explicit_database(repo_root: Path) -> None:
    from alembic import command
    from alembic.config import Config

    with pytest.raises(RuntimeError, match="explicit protected or temporary"):
        command.upgrade(Config(repo_root / "alembic.ini"), "head")


def test_runtime_directory_verification_does_not_create_missing_production_path(
    tmp_path: Path,
) -> None:
    settings = DatabaseRuntimeSettings(
        tmp_path / "state/db.sqlite",
        tmp_path / "missing-run",
        verify_runtime_directory=True,
    )
    with pytest.raises(DatabaseRuntimeError, match="absent"):
        import asyncio

        asyncio.run(create_database_runtime(settings))
    assert not settings.runtime_directory.exists()


def test_stopped_service_upgrade_and_current_revision_commands(
    tmp_path: Path, repo_root: Path
) -> None:
    database = tmp_path / "state/binnacle.db"
    database.parent.mkdir()
    settings = DatabaseRuntimeSettings(database, tmp_path / "run", verify_runtime_directory=False)
    upgrade_database(settings, project_root=repo_root)
    current_revision(settings, project_root=repo_root)
    import sqlite3

    connection = sqlite3.connect(database)
    try:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    finally:
        connection.close()
    assert revision == ("0001_durable_operation_kernel",)


@pytest.mark.anyio
async def test_runtime_configuration_and_filesystem_attacks_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(DatabaseRuntimeError, match="busy timeout"):
        await create_database_runtime(
            DatabaseRuntimeSettings(
                tmp_path / "bad-timeout.db",
                tmp_path / "run-timeout",
                busy_timeout_ms=99,
                verify_runtime_directory=False,
            )
        )
    with pytest.raises(DatabaseRuntimeError, match="autocheckpoint"):
        await create_database_runtime(
            DatabaseRuntimeSettings(
                tmp_path / "bad-checkpoint.db",
                tmp_path / "run-checkpoint",
                wal_autocheckpoint_pages=99,
                verify_runtime_directory=False,
            )
        )

    target = tmp_path / "target.db"
    target.touch()
    link = tmp_path / "linked.db"
    link.symlink_to(target)
    with pytest.raises(DatabaseRuntimeError, match="symlink"):
        await create_database_runtime(
            DatabaseRuntimeSettings(link, tmp_path / "run-link", verify_runtime_directory=False)
        )

    unsafe_file = tmp_path / "not-a-directory"
    unsafe_file.touch()
    with pytest.raises(DatabaseRuntimeError, match="unsafe"):
        verify_runtime_directory(unsafe_file)
    broad = tmp_path / "broad"
    broad.mkdir(mode=0o777)
    broad.chmod(0o777)
    with pytest.raises(DatabaseRuntimeError, match="broader"):
        verify_runtime_directory(broad)

    protected = tmp_path / "protected"
    protected.mkdir(mode=0o750)
    protected.chmod(0o750)
    current_gid = os.getegid()
    monkeypatch.setattr("binnacle.adapters.sqlite.engine.os.getegid", lambda: current_gid + 1)
    with pytest.raises(DatabaseRuntimeError, match="primary group"):
        verify_runtime_directory(protected)
