"""Fresh migration, schema constraints, pragmas, and runtime-lock tests."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from tests.phase4_support import intent, migrate_database, owner

from binnacle.adapters.sqlite.engine import (
    DatabaseRuntimeError,
    DatabaseRuntimeSettings,
    close_database_runtime,
    create_database_runtime,
    verify_database_runtime,
    verify_runtime_directory,
)
from binnacle.adapters.sqlite.migrations import current_revision, upgrade_database
from binnacle.adapters.sqlite.operation_store import SqliteOperationStore
from binnacle.domain.idempotency import IdempotencyKeyMode, validate_and_digest_key
from binnacle.ports.operation_store import CreateOrFindRequest

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
    "probe_path_ledger": {
        "relative_path",
        "generation_high_water",
        "terminal_history_count",
        "terminal_history_sha256",
        "active_artifact_id",
        "active_generation",
        "active_create_operation_id",
        "ledger_version",
        "updated_at",
    },
    "probe_artifacts": {
        "artifact_id",
        "relative_path",
        "path_generation",
        "owner_controller_id",
        "owner_controller_epoch",
        "content_sha256",
        "byte_count",
        "state",
        "create_operation_id",
        "active_cleanup_operation_id",
        "removed_by_cleanup_operation_id",
        "created_at",
        "updated_at",
        "removed_at",
        "file_identity_digest",
    },
    "probe_operations": {
        "operation_id",
        "probe_operation",
        "prepared_binding_id",
        "caller_binding_id",
        "artifact_id",
        "relative_path",
        "expected_content_sha256",
        "expected_byte_count",
        "prepared_state_binding_sha256",
        "created_at",
    },
    "registered_workspaces": {
        "workspace_id",
        "profile_sha256",
        "root_identity_sha256",
        "mount_identity_sha256",
        "root_device",
        "root_inode",
        "mount_id",
        "mount_device",
        "filesystem_type",
        "owner_uid",
        "owner_gid",
        "mode",
        "primitive_profile_version",
        "registration_version",
        "registered_at",
        "updated_at",
    },
    "development_sessions": {
        "session_id",
        "begin_operation_id",
        "state",
        "state_version",
        "activation_closure",
        "activation_closure_version",
        "controller_id",
        "controller_epoch",
        "device_id",
        "device_epoch",
        "workspace_id",
        "workspace_profile_sha256",
        "workspace_root_identity_sha256",
        "workspace_mount_identity_sha256",
        "policy_version",
        "contract_profile_sha256",
        "objective_sha256",
        "created_at",
        "updated_at",
        "expires_at",
        "trusted_time_generation",
        "activation_boot_id_digest",
        "monotonic_deadline_ns",
        "started_at",
        "terminal_at",
        "terminal_reason",
        "activation_effect_reference",
        "activation_effect_reference_sha256",
    },
    "workspace_operations": {
        "operation_id",
        "session_id",
        "workspace_id",
        "mutation_kind",
        "object_kind",
        "source_path_sha256",
        "target_path_sha256",
        "expected_object_sha256",
        "expected_content_sha256",
        "expected_link_count",
        "expected_mount_identity_sha256",
        "proposed_content_sha256",
        "proposed_byte_count",
        "state_binding_sha256",
        "staging_reference",
        "staging_reference_sha256",
        "primitive_profile_version",
        "created_at",
        "updated_at",
    },
    "workspace_mutation_fences": {
        "workspace_id",
        "fence_version",
        "active_operation_id",
        "active_contract",
        "acquired_at",
        "updated_at",
    },
    "command_operations": {
        "operation_id",
        "session_id",
        "workspace_id",
        "controller_epoch",
        "device_epoch",
        "development_session_state_version",
        "development_session_closure_sha256",
        "ticket_id",
        "ticket_sha256",
        "single_use_nonce_sha256",
        "ticket_issued_at",
        "ticket_expires_at",
        "ticket_boot_id_digest",
        "ticket_monotonic_deadline_ns",
        "admission_record_id",
        "command_profile_id",
        "workspace_profile_sha256",
        "workspace_root_identity_sha256",
        "workspace_mount_identity_sha256",
        "workspace_fence_version",
        "executable_identity_sha256",
        "argv_sha256",
        "cwd_sha256",
        "environment_sha256",
        "stdin_sha256",
        "stdin_reference_sha256",
        "workspace_script_sha256",
        "mount_plan_sha256",
        "policy_sha256",
        "resource_plan_sha256",
        "sandbox_plan_sha256",
        "process_isolation_plan_sha256",
        "network_plan_sha256",
        "record_version",
        "acceptance_state",
        "execution_id",
        "executor_reference",
        "accepted_receipt_sha256",
        "no_accept_reference",
        "no_accept_receipt_sha256",
        "phase7_cancel_generation",
        "supervisor_ack_cancel_generation",
        "supervisor_cancel_disposition",
        "supervisor_evidence_generation",
        "supervisor_cancel_evidence_sha256",
        "last_executor_state",
        "terminal_evidence_sha256",
        "descendants_stopped",
        "output_finalized",
        "private_resources_cleaned",
        "cleanup_evidence_sha256",
        "closure_state",
        "created_at",
        "updated_at",
        "last_reconciled_at",
    },
    "command_cancel_requests": {
        "cancel_operation_id",
        "command_operation_id",
        "cancel_generation",
        "request_fingerprint_sha256",
        "created_at",
    },
    "git_operations": {
        "operation_id",
        "session_id",
        "workspace_id",
        "operation_kind",
        "repository_profile_id",
        "repository_profile_sha256",
        "repository_safety_sha256",
        "repository_state_binding_sha256",
        "workspace_fence_version",
        "source_ref",
        "destination_ref",
        "expected_old_oid_algorithm",
        "expected_old_oid_hex",
        "desired_oid_algorithm",
        "desired_oid_hex",
        "request_sha256",
        "commit_request_sha256",
        "remote_request_sha256",
        "credential_reference_sha256",
        "current_stage_generation",
        "aggregate_effect_knowledge",
        "state",
        "created_at",
        "updated_at",
        "last_reconciled_at",
    },
    "git_operation_stages": {
        "operation_id",
        "stage_generation",
        "member_id",
        "stage_kind",
        "effect_role",
        "input_sha256",
        "pre_state_sha256",
        "member_ticket_id",
        "member_ticket_sha256",
        "acceptance_state",
        "execution_id",
        "crossing_state",
        "effect_knowledge",
        "before_oid_algorithm",
        "before_oid_hex",
        "after_oid_algorithm",
        "after_oid_hex",
        "cancel_generation",
        "acknowledged_cancel_generation",
        "executor_evidence_generation",
        "cleanup_complete",
        "cleanup_evidence_sha256",
        "state",
        "created_at",
        "updated_at",
        "closed_at",
    },
    "git_commit_evidence": {
        "operation_id",
        "commit_oid_algorithm",
        "commit_oid_hex",
        "tree_oid_algorithm",
        "tree_oid_hex",
        "parent_oid_algorithm",
        "parent_oid_hex",
        "author_sha256",
        "committer_sha256",
        "message_sha256",
        "preimage_sha256",
        "author_at",
        "committer_at",
        "signer_profile_sha256",
        "signer_public_fingerprint",
        "signature_sha256",
        "signature_verified",
        "object_imported",
        "branch_cas_complete",
        "expected_main_index_identity_sha256",
        "expected_main_index_tree_oid_algorithm",
        "expected_main_index_tree_oid_hex",
        "expected_main_index_sha256",
        "target_main_index_tree_oid_algorithm",
        "target_main_index_tree_oid_hex",
        "target_main_index_sha256",
        "selected_worktree_snapshot_sha256",
        "main_index_publication_state",
        "main_index_publication_receipt_sha256",
        "worktree_evidence_sha256",
        "created_at",
        "updated_at",
    },
    "git_remote_evidence": {
        "operation_id",
        "remote_profile_sha256",
        "destination_sha256",
        "outbound_closure_sha256",
        "source_ref",
        "destination_ref",
        "expected_remote_state",
        "expected_oid_algorithm",
        "expected_oid_hex",
        "desired_oid_algorithm",
        "desired_oid_hex",
        "observed_oid_algorithm",
        "observed_oid_hex",
        "transport_state",
        "transport_evidence_sha256",
        "credential_use_evidence_sha256",
        "remote_reconciled",
        "credential_cleanup_complete",
        "created_at",
        "updated_at",
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
        assert health.revision == "0005_git_operations"
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
            transition_checks = await connection.run_sync(
                lambda sync: {
                    item["name"]
                    for item in inspect(sync).get_check_constraints("operation_transitions")
                }
            )
            indexes = await connection.run_sync(
                lambda sync: {
                    table: {item["name"] for item in inspect(sync).get_indexes(table)}
                    for table in (
                        "operations",
                        "idempotency_bindings",
                        "payload_objects",
                        "probe_artifacts",
                        "development_sessions",
                        "workspace_operations",
                    )
                }
            )
            probe_fks = await connection.run_sync(
                lambda sync: {
                    table: inspect(sync).get_foreign_keys(table)
                    for table in ("probe_path_ledger", "probe_artifacts", "probe_operations")
                }
            )
            probe_checks = await connection.run_sync(
                lambda sync: {
                    table: {item["name"] for item in inspect(sync).get_check_constraints(table)}
                    for table in ("probe_path_ledger", "probe_artifacts", "probe_operations")
                }
            )
            phase6_fks = await connection.run_sync(
                lambda sync: {
                    table: inspect(sync).get_foreign_keys(table)
                    for table in (
                        "development_sessions",
                        "workspace_operations",
                        "workspace_mutation_fences",
                    )
                }
            )
            phase6_checks = await connection.run_sync(
                lambda sync: {
                    table: {item["name"] for item in inspect(sync).get_check_constraints(table)}
                    for table in (
                        "registered_workspaces",
                        "development_sessions",
                        "workspace_operations",
                        "workspace_mutation_fences",
                    )
                }
            )
        assert tables == set(EXPECTED_COLUMNS) | {"alembic_version"}
        assert columns == EXPECTED_COLUMNS
        assert {tuple(item["constrained_columns"]) for item in policy_fks} == {("operation_id",)}
        assert ("operation_id",) in {tuple(item["column_names"]) for item in policy_unique}
        assert "ck_bindings_owner_shape" in binding_checks
        assert "ck_kernel_meta_time_monotonic" in kernel_checks
        assert "ck_kernel_meta_admission_safe" in kernel_checks
        assert "ck_operation_transitions_shape" in transition_checks
        assert indexes == {
            "operations": {"ix_operations_state"},
            "idempotency_bindings": {"ix_bindings_operation"},
            "payload_objects": {"ix_payload_owner"},
            "probe_artifacts": {"uq_probe_artifacts_live_relative_path"},
            "development_sessions": {"uq_development_sessions_live_slot"},
            "workspace_operations": {"ix_workspace_operations_session"},
        }
        assert {item["name"] for item in probe_fks["probe_path_ledger"]} == {
            "fk_probe_ledger_active_artifact",
            "fk_probe_ledger_active_create_operation",
        }
        active_artifact_fk = next(
            item
            for item in probe_fks["probe_path_ledger"]
            if item["name"] == "fk_probe_ledger_active_artifact"
        )
        assert active_artifact_fk["options"] == {"deferrable": True, "initially": "DEFERRED"}
        assert "ck_probe_ledger_active_shape" in probe_checks["probe_path_ledger"]
        assert "ck_probe_artifacts_state_shape" in probe_checks["probe_artifacts"]
        assert "ck_probe_operations_byte_shape" in probe_checks["probe_operations"]
        assert {
            tuple(item["constrained_columns"]) for item in phase6_fks["development_sessions"]
        } == {("begin_operation_id",), ("controller_id", "controller_epoch"), ("workspace_id",)}
        assert {
            tuple(item["constrained_columns"]) for item in phase6_fks["workspace_operations"]
        } == {("operation_id",), ("session_id",), ("workspace_id",)}
        assert {
            tuple(item["constrained_columns"]) for item in phase6_fks["workspace_mutation_fences"]
        } == {("active_operation_id",), ("workspace_id",)}
        assert "ck_registered_workspaces_digests" in phase6_checks["registered_workspaces"]
        assert "ck_development_sessions_version_shape" in phase6_checks["development_sessions"]
        assert "ck_workspace_operations_path_shape" in phase6_checks["workspace_operations"]
        assert "ck_workspace_fences_owner_shape" in phase6_checks["workspace_mutation_fences"]
    finally:
        await close_database_runtime(runtime)


@pytest.mark.anyio
async def test_transition_shape_constraint_rejects_invalid_version_rows(
    tmp_path: Path, repo_root: Path
) -> None:
    database = tmp_path / "state/binnacle.db"
    database.parent.mkdir()
    migrate_database(database, repo_root)
    runtime = await create_database_runtime(
        DatabaseRuntimeSettings(database, tmp_path / "run", verify_runtime_directory=False)
    )
    try:
        store = SqliteOperationStore(runtime)
        await store.initialize_kernel(device_id="device-fixture", audit_stream_id="stream-fixture")
        key = validate_and_digest_key("ab" * 32, IdempotencyKeyMode.CALLER_KEY)
        created = await store.create_or_find(
            CreateOrFindRequest(key, owner(), intent(), "internal.synthetic", "1.0.0")
        )
        assert created.operation is not None
        operation_id = created.operation.operation_id
        insert = text(
            "INSERT INTO operation_transitions "
            "(operation_id, state_version, from_state, to_state, effect_knowledge, "
            "terminality, reason_code, error_code, recorded_at, runtime_build_sha256) "
            "VALUES (:operation_id, :state_version, :from_state, :to_state, 'none', "
            "'non_terminal', 'invalid_fixture', NULL, CURRENT_TIMESTAMP, :runtime_build)"
        )
        invalid_shapes = (
            {"state_version": 1, "from_state": "received", "to_state": "received"},
            {"state_version": 1, "from_state": None, "to_state": "failed"},
            {"state_version": 2, "from_state": None, "to_state": "authorised"},
        )
        async with runtime.engine.connect() as connection:
            await connection.execute(
                text("DELETE FROM operation_transitions WHERE operation_id = :operation_id"),
                {"operation_id": operation_id},
            )
            await connection.commit()
            for shape in invalid_shapes:
                with pytest.raises(IntegrityError):
                    await connection.execute(
                        insert,
                        {
                            "operation_id": operation_id,
                            "runtime_build": "b" * 64,
                            **shape,
                        },
                    )
                await connection.rollback()
    finally:
        await close_database_runtime(runtime)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("state", "file_identity", "active_cleanup", "removed_at", "active"),
    (
        ("reserved", "b" * 64, None, None, True),
        ("uncertain", None, "self", None, True),
        ("removed", None, None, "2026-08-12 00:00:00", False),
    ),
)
async def test_probe_artifact_state_shape_rejects_contradictory_rows(
    tmp_path: Path,
    repo_root: Path,
    state: str,
    file_identity: str | None,
    active_cleanup: str | None,
    removed_at: str | None,
    active: bool,
) -> None:
    database = tmp_path / "state/binnacle.db"
    database.parent.mkdir()
    migrate_database(database, repo_root)
    runtime = await create_database_runtime(
        DatabaseRuntimeSettings(database, tmp_path / "run", verify_runtime_directory=False)
    )
    try:
        store = SqliteOperationStore(runtime)
        await store.initialize_kernel(device_id="device-fixture", audit_stream_id="stream-fixture")
        created = await store.create_or_find(
            CreateOrFindRequest(
                validate_and_digest_key("cd" * 32, IdempotencyKeyMode.CALLER_KEY),
                owner(),
                intent(),
                "internal.synthetic",
                "1.0.0",
            )
        )
        assert created.operation is not None
        operation_id = created.operation.operation_id
        artifact_id = "artifact-state-shape"
        async with runtime.engine.connect() as connection:
            await connection.execute(
                text(
                    "INSERT INTO probe_path_ledger "
                    "(relative_path,generation_high_water,terminal_history_count,"
                    "terminal_history_sha256,active_artifact_id,active_generation,"
                    "active_create_operation_id,ledger_version,updated_at) VALUES "
                    "('probe.txt',1,:terminal_count,:history,:artifact_id,:generation,"
                    ":create_operation,1,CURRENT_TIMESTAMP)"
                ),
                {
                    "terminal_count": 0 if active else 1,
                    "history": "a" * 64,
                    "artifact_id": artifact_id if active else None,
                    "generation": 1 if active else None,
                    "create_operation": operation_id if active else None,
                },
            )
            with pytest.raises(IntegrityError):
                await connection.execute(
                    text(
                        "INSERT INTO probe_artifacts "
                        "(artifact_id,relative_path,path_generation,owner_controller_id,"
                        "owner_controller_epoch,content_sha256,byte_count,state,"
                        "create_operation_id,active_cleanup_operation_id,"
                        "removed_by_cleanup_operation_id,created_at,updated_at,removed_at,"
                        "file_identity_digest) VALUES "
                        "(:artifact_id,'probe.txt',1,:controller_id,1,:content,4,:state,"
                        ":create_operation,:active_cleanup,NULL,CURRENT_TIMESTAMP,"
                        "CURRENT_TIMESTAMP,:removed_at,:file_identity)"
                    ),
                    {
                        "artifact_id": artifact_id,
                        "controller_id": created.operation.owner.controller_id,
                        "content": "a" * 64,
                        "state": state,
                        "create_operation": operation_id,
                        "active_cleanup": (
                            operation_id if active_cleanup == "self" else active_cleanup
                        ),
                        "removed_at": removed_at,
                        "file_identity": file_identity,
                    },
                )
            await connection.rollback()
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
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()
    with pytest.raises(RuntimeError, match="unmanaged"):
        migrate_database(database, repo_root)


def test_populated_phase4_database_upgrades_without_rewriting_existing_rows(
    tmp_path: Path, repo_root: Path
) -> None:
    from alembic import command
    from alembic.config import Config

    database = tmp_path / "upgrade.db"
    config = Config(repo_root / "alembic.ini")
    config.set_main_option("script_location", str(repo_root / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "0001_durable_operation_kernel")
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO controller_owners "
            "(controller_id, controller_epoch, controller_profile_id, "
            "controller_profile_version, first_seen_at, last_seen_at, active) "
            "VALUES (?, 1, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)",
            ("controller-preserved", "profile-preserved", "1.0.0"),
        )
        connection.commit()
    finally:
        connection.close()

    command.upgrade(config, "head")
    connection = sqlite3.connect(database)
    try:
        owner_row = connection.execute(
            "SELECT controller_id, controller_epoch FROM controller_owners"
        ).fetchone()
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        phase5_counts = tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "probe_operations",
                "probe_artifacts",
                "probe_path_ledger",
                "registered_workspaces",
                "development_sessions",
                "workspace_operations",
                "workspace_mutation_fences",
            )
        )
    finally:
        connection.close()

    assert owner_row == ("controller-preserved", 1)
    assert revision == ("0005_git_operations",)
    assert phase5_counts == (0, 0, 0, 0, 0, 0, 0)


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
    assert revision == ("0005_git_operations",)


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
