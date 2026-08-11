"""Add independently anchored Phase 5 write-probe state.

Revision ID: 0002_write_probe_state
Revises: 0001_durable_operation_kernel
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_write_probe_state"
down_revision = "0001_durable_operation_kernel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "probe_path_ledger",
        sa.Column("relative_path", sa.String(length=255), nullable=False),
        sa.Column("generation_high_water", sa.Integer(), nullable=False),
        sa.Column("terminal_history_count", sa.Integer(), nullable=False),
        sa.Column("terminal_history_sha256", sa.String(length=64), nullable=False),
        sa.Column("active_artifact_id", sa.String(length=160), nullable=True),
        sa.Column("active_generation", sa.Integer(), nullable=True),
        sa.Column("active_create_operation_id", sa.String(length=160), nullable=True),
        sa.Column("ledger_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "generation_high_water >= 0", name="ck_probe_ledger_generation_high_water"
        ),
        sa.CheckConstraint(
            "terminal_history_count >= 0 AND terminal_history_count <= generation_high_water",
            name="ck_probe_ledger_terminal_count",
        ),
        sa.CheckConstraint("ledger_version >= 1", name="ck_probe_ledger_version"),
        sa.CheckConstraint(
            "length(terminal_history_sha256) = 64",
            name="ck_probe_ledger_history_digest",
        ),
        sa.CheckConstraint(
            "(active_artifact_id IS NULL AND active_generation IS NULL AND "
            "active_create_operation_id IS NULL AND "
            "terminal_history_count = generation_high_water) OR "
            "(active_artifact_id IS NOT NULL AND active_generation IS NOT NULL AND "
            "active_create_operation_id IS NOT NULL AND active_generation = "
            "generation_high_water AND terminal_history_count = active_generation - 1)",
            name="ck_probe_ledger_active_shape",
        ),
        sa.ForeignKeyConstraint(
            ["active_artifact_id"],
            ["probe_artifacts.artifact_id"],
            name="fk_probe_ledger_active_artifact",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["active_create_operation_id"],
            ["operations.operation_id"],
            name="fk_probe_ledger_active_create_operation",
        ),
        sa.PrimaryKeyConstraint("relative_path", name="pk_probe_path_ledger"),
        sa.UniqueConstraint("active_artifact_id", name="uq_probe_ledger_active_artifact"),
    )
    op.create_table(
        "probe_artifacts",
        sa.Column("artifact_id", sa.String(length=160), nullable=False),
        sa.Column("relative_path", sa.String(length=255), nullable=False),
        sa.Column("path_generation", sa.Integer(), nullable=False),
        sa.Column("owner_controller_id", sa.String(length=160), nullable=False),
        sa.Column("owner_controller_epoch", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("create_operation_id", sa.String(length=160), nullable=False),
        sa.Column("active_cleanup_operation_id", sa.String(length=160), nullable=True),
        sa.Column("removed_by_cleanup_operation_id", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("file_identity_digest", sa.String(length=64), nullable=True),
        sa.CheckConstraint("path_generation >= 1", name="ck_probe_artifacts_generation"),
        sa.CheckConstraint("owner_controller_epoch >= 1", name="ck_probe_artifacts_owner_epoch"),
        sa.CheckConstraint(
            "byte_count >= 0 AND byte_count <= 65536", name="ck_probe_artifacts_bytes"
        ),
        sa.CheckConstraint(
            "state IN ('reserved','created','removed','abandoned','uncertain')",
            name="ck_probe_artifacts_state",
        ),
        sa.CheckConstraint(
            "length(content_sha256) = 64 AND "
            "(file_identity_digest IS NULL OR length(file_identity_digest) = 64)",
            name="ck_probe_artifacts_digests",
        ),
        sa.CheckConstraint(
            "(state IN ('reserved','uncertain') AND file_identity_digest IS NULL AND "
            "active_cleanup_operation_id IS NULL AND removed_at IS NULL AND "
            "removed_by_cleanup_operation_id IS NULL) OR "
            "(state = 'created' AND file_identity_digest IS NOT NULL AND removed_at IS NULL "
            "AND removed_by_cleanup_operation_id IS NULL) OR "
            "(state = 'removed' AND file_identity_digest IS NOT NULL AND "
            "removed_at IS NOT NULL AND "
            "active_cleanup_operation_id IS NULL) OR "
            "(state = 'abandoned' AND removed_at IS NOT NULL AND "
            "file_identity_digest IS NULL AND active_cleanup_operation_id IS NULL AND "
            "removed_by_cleanup_operation_id IS NULL)",
            name="ck_probe_artifacts_state_shape",
        ),
        sa.ForeignKeyConstraint(
            ["relative_path"],
            ["probe_path_ledger.relative_path"],
            name="fk_probe_artifacts_ledger",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["owner_controller_id", "owner_controller_epoch"],
            ["controller_owners.controller_id", "controller_owners.controller_epoch"],
            name="fk_probe_artifacts_owner",
        ),
        sa.ForeignKeyConstraint(
            ["create_operation_id"],
            ["operations.operation_id"],
            name="fk_probe_artifacts_create_operation",
        ),
        sa.ForeignKeyConstraint(
            ["active_cleanup_operation_id"],
            ["operations.operation_id"],
            name="fk_probe_artifacts_active_cleanup",
        ),
        sa.ForeignKeyConstraint(
            ["removed_by_cleanup_operation_id"],
            ["operations.operation_id"],
            name="fk_probe_artifacts_removed_by_cleanup",
        ),
        sa.PrimaryKeyConstraint("artifact_id", name="pk_probe_artifacts"),
        sa.UniqueConstraint(
            "relative_path", "path_generation", name="uq_probe_artifacts_path_generation"
        ),
        sa.UniqueConstraint("create_operation_id", name="uq_probe_artifacts_create_operation"),
        sa.UniqueConstraint(
            "active_cleanup_operation_id", name="uq_probe_artifacts_active_cleanup"
        ),
        sa.UniqueConstraint(
            "removed_by_cleanup_operation_id", name="uq_probe_artifacts_removed_by_cleanup"
        ),
    )
    op.create_index(
        "uq_probe_artifacts_live_relative_path",
        "probe_artifacts",
        ["relative_path"],
        unique=True,
        sqlite_where=sa.text("state IN ('reserved','created','uncertain')"),
    )
    op.create_table(
        "probe_operations",
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("probe_operation", sa.String(length=16), nullable=False),
        sa.Column("prepared_binding_id", sa.String(length=160), nullable=False),
        sa.Column("caller_binding_id", sa.String(length=160), nullable=False),
        sa.Column("artifact_id", sa.String(length=160), nullable=False),
        sa.Column("relative_path", sa.String(length=255), nullable=False),
        sa.Column("expected_content_sha256", sa.String(length=64), nullable=False),
        sa.Column("expected_byte_count", sa.Integer(), nullable=True),
        sa.Column("prepared_state_binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "probe_operation IN ('write','cleanup')", name="ck_probe_operations_kind"
        ),
        sa.CheckConstraint(
            "length(expected_content_sha256) = 64 AND length(prepared_state_binding_sha256) = 64",
            name="ck_probe_operations_digests",
        ),
        sa.CheckConstraint(
            "(probe_operation = 'write' AND expected_byte_count IS NOT NULL AND "
            "expected_byte_count >= 0 AND expected_byte_count <= 65536) OR "
            "(probe_operation = 'cleanup' AND expected_byte_count IS NULL)",
            name="ck_probe_operations_byte_shape",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.operation_id"],
            name="fk_probe_operations_operation",
        ),
        sa.ForeignKeyConstraint(
            ["prepared_binding_id"],
            ["idempotency_bindings.binding_id"],
            name="fk_probe_operations_prepared_binding",
        ),
        sa.ForeignKeyConstraint(
            ["caller_binding_id"],
            ["idempotency_bindings.binding_id"],
            name="fk_probe_operations_caller_binding",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["probe_artifacts.artifact_id"],
            name="fk_probe_operations_artifact",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("operation_id", name="pk_probe_operations"),
        sa.UniqueConstraint("prepared_binding_id", name="uq_probe_operations_prepared_binding"),
        sa.UniqueConstraint("caller_binding_id", name="uq_probe_operations_caller_binding"),
    )
    op.execute(
        """
        CREATE TRIGGER trg_probe_terminal_artifact_immutable
        BEFORE UPDATE ON probe_artifacts
        WHEN OLD.state IN ('removed','abandoned') AND (
            NEW.artifact_id IS NOT OLD.artifact_id OR
            NEW.relative_path IS NOT OLD.relative_path OR
            NEW.path_generation IS NOT OLD.path_generation OR
            NEW.owner_controller_id IS NOT OLD.owner_controller_id OR
            NEW.owner_controller_epoch IS NOT OLD.owner_controller_epoch OR
            NEW.content_sha256 IS NOT OLD.content_sha256 OR
            NEW.byte_count IS NOT OLD.byte_count OR
            NEW.state IS NOT OLD.state OR
            NEW.create_operation_id IS NOT OLD.create_operation_id OR
            NEW.active_cleanup_operation_id IS NOT OLD.active_cleanup_operation_id OR
            NEW.removed_by_cleanup_operation_id IS NOT OLD.removed_by_cleanup_operation_id OR
            NEW.created_at IS NOT OLD.created_at OR
            NEW.removed_at IS NOT OLD.removed_at OR
            NEW.file_identity_digest IS NOT OLD.file_identity_digest
        )
        BEGIN
            SELECT RAISE(ABORT, 'terminal probe artifact is immutable');
        END
        """
    )
    op.execute("UPDATE kernel_meta SET schema_generation = 2, updated_at = CURRENT_TIMESTAMP")


def downgrade() -> None:
    op.execute("UPDATE kernel_meta SET schema_generation = 1, updated_at = CURRENT_TIMESTAMP")
    op.execute("DROP TRIGGER IF EXISTS trg_probe_terminal_artifact_immutable")
    op.drop_table("probe_operations")
    op.drop_index("uq_probe_artifacts_live_relative_path", table_name="probe_artifacts")
    op.drop_table("probe_artifacts")
    op.drop_table("probe_path_ledger")
