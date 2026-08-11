"""Add authoritative Phase 6 development-workspace state.

Revision ID: 0003_development_workspace
Revises: 0002_write_probe_state

The migration creates schema only.  It intentionally does not inspect a checkout,
register a workspace, or synthesize a mutation fence: registration is a separate
stopped-service owner operation and missing rows remain observable integrity failures.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_development_workspace"
down_revision = "0002_write_probe_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registered_workspaces",
        sa.Column("workspace_id", sa.String(length=160), nullable=False),
        sa.Column("profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("root_identity_sha256", sa.String(length=64), nullable=False),
        sa.Column("mount_identity_sha256", sa.String(length=64), nullable=False),
        sa.Column("root_device", sa.Integer(), nullable=False),
        sa.Column("root_inode", sa.Integer(), nullable=False),
        sa.Column("mount_id", sa.Integer(), nullable=False),
        sa.Column("mount_device", sa.Integer(), nullable=False),
        sa.Column("filesystem_type", sa.String(length=64), nullable=False),
        sa.Column("owner_uid", sa.Integer(), nullable=False),
        sa.Column("owner_gid", sa.Integer(), nullable=False),
        sa.Column("mode", sa.Integer(), nullable=False),
        sa.Column("primitive_profile_version", sa.String(length=64), nullable=False),
        sa.Column("registration_version", sa.Integer(), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(profile_sha256) = 64 AND length(root_identity_sha256) = 64 "
            "AND length(mount_identity_sha256) = 64",
            name="ck_registered_workspaces_digests",
        ),
        sa.CheckConstraint(
            "length(workspace_id) >= 1 AND length(workspace_id) <= 160",
            name="ck_registered_workspaces_identifier",
        ),
        sa.CheckConstraint(
            "root_device >= 0 AND root_inode >= 1 AND mount_id >= 1 AND mount_device >= 0",
            name="ck_registered_workspaces_identity",
        ),
        sa.CheckConstraint(
            "owner_uid >= 0 AND owner_gid >= 0 AND mode >= 0 AND mode <= 4095",
            name="ck_registered_workspaces_ownership",
        ),
        sa.CheckConstraint(
            "length(filesystem_type) >= 1 AND length(filesystem_type) <= 64 "
            "AND length(primitive_profile_version) >= 1 "
            "AND length(primitive_profile_version) <= 64",
            name="ck_registered_workspaces_profile",
        ),
        sa.CheckConstraint("registration_version >= 1", name="ck_registered_workspaces_version"),
        sa.CheckConstraint(
            "updated_at >= registered_at", name="ck_registered_workspaces_time_order"
        ),
        sa.PrimaryKeyConstraint("workspace_id", name="pk_registered_workspaces"),
        sa.UniqueConstraint("root_identity_sha256", name="uq_registered_workspaces_root_identity"),
    )
    op.create_table(
        "development_sessions",
        sa.Column("session_id", sa.String(length=160), nullable=False),
        sa.Column("begin_operation_id", sa.String(length=160), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("activation_closure", sa.String(length=16), nullable=False),
        sa.Column("activation_closure_version", sa.Integer(), nullable=False),
        sa.Column("controller_id", sa.String(length=160), nullable=False),
        sa.Column("controller_epoch", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=160), nullable=False),
        sa.Column("device_epoch", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.String(length=160), nullable=False),
        sa.Column("workspace_profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("workspace_root_identity_sha256", sa.String(length=64), nullable=False),
        sa.Column("workspace_mount_identity_sha256", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("contract_profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("objective_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trusted_time_generation", sa.Integer(), nullable=False),
        sa.Column("activation_boot_id_digest", sa.String(length=64), nullable=False),
        sa.Column("monotonic_deadline_ns", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.String(length=160), nullable=True),
        sa.Column("activation_effect_reference", sa.String(length=160), nullable=True),
        sa.Column("activation_effect_reference_sha256", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "state IN ('pending','active','ended','expired','revoked')",
            name="ck_development_sessions_state",
        ),
        sa.CheckConstraint(
            "activation_closure IN ('pending','complete')",
            name="ck_development_sessions_activation_closure",
        ),
        sa.CheckConstraint(
            "state_version >= 1 AND activation_closure_version >= 1",
            name="ck_development_sessions_versions",
        ),
        sa.CheckConstraint(
            "length(session_id) >= 1 AND length(session_id) <= 160 "
            "AND length(begin_operation_id) >= 1 AND length(begin_operation_id) <= 160 "
            "AND length(controller_id) >= 1 AND length(controller_id) <= 160 "
            "AND length(device_id) >= 1 AND length(device_id) <= 160 "
            "AND length(workspace_id) >= 1 AND length(workspace_id) <= 160 "
            "AND length(policy_version) >= 1 AND length(policy_version) <= 64",
            name="ck_development_sessions_identifiers",
        ),
        sa.CheckConstraint(
            "controller_epoch >= 1 AND device_epoch >= 1 "
            "AND trusted_time_generation >= 1 AND monotonic_deadline_ns >= 0",
            name="ck_development_sessions_epochs",
        ),
        sa.CheckConstraint(
            "length(workspace_profile_sha256) = 64 "
            "AND length(workspace_root_identity_sha256) = 64 "
            "AND length(workspace_mount_identity_sha256) = 64 "
            "AND length(contract_profile_sha256) = 64 "
            "AND length(objective_sha256) = 64 "
            "AND length(activation_boot_id_digest) = 64 "
            "AND (activation_effect_reference_sha256 IS NULL "
            "OR length(activation_effect_reference_sha256) = 64)",
            name="ck_development_sessions_digests",
        ),
        sa.CheckConstraint(
            "expires_at > created_at AND updated_at >= created_at "
            "AND (started_at IS NULL OR (started_at >= created_at AND started_at < expires_at)) "
            "AND (terminal_at IS NULL OR terminal_at >= created_at) "
            "AND (started_at IS NULL OR updated_at >= started_at) "
            "AND (terminal_at IS NULL OR updated_at >= terminal_at) "
            "AND (started_at IS NULL OR terminal_at IS NULL OR terminal_at >= started_at)",
            name="ck_development_sessions_time_order",
        ),
        sa.CheckConstraint(
            "(activation_effect_reference IS NULL "
            "AND activation_effect_reference_sha256 IS NULL) OR "
            "(activation_effect_reference IS NOT NULL "
            "AND activation_effect_reference_sha256 IS NOT NULL)",
            name="ck_development_sessions_effect_reference",
        ),
        sa.CheckConstraint(
            "((started_at IS NULL AND activation_effect_reference IS NULL) OR "
            "(started_at IS NOT NULL AND activation_effect_reference IS NOT NULL)) "
            "AND (terminal_reason IS NULL OR "
            "(length(terminal_reason) >= 1 AND length(terminal_reason) <= 160)) "
            "AND (activation_effect_reference IS NULL OR "
            "(length(activation_effect_reference) >= 1 "
            "AND length(activation_effect_reference) <= 160))",
            name="ck_development_sessions_history_shape",
        ),
        sa.CheckConstraint(
            "(state = 'pending' AND started_at IS NULL AND terminal_at IS NULL "
            "AND terminal_reason IS NULL AND activation_closure = 'pending' "
            "AND activation_closure_version = 1 "
            "AND activation_effect_reference IS NULL) OR "
            "(state = 'active' AND started_at IS NOT NULL AND terminal_at IS NULL "
            "AND terminal_reason IS NULL AND activation_effect_reference IS NOT NULL) OR "
            "(state IN ('ended','expired','revoked') AND terminal_at IS NOT NULL "
            "AND terminal_reason IS NOT NULL)",
            name="ck_development_sessions_state_shape",
        ),
        sa.CheckConstraint(
            "(activation_closure = 'pending' AND activation_closure_version = 1) OR "
            "(activation_closure = 'complete' AND activation_closure_version = 2)",
            name="ck_development_sessions_closure_shape",
        ),
        sa.CheckConstraint(
            "(state = 'pending' AND state_version = 1) OR "
            "(state = 'active' AND activation_closure = 'pending' "
            "AND state_version = 2) OR "
            "(state = 'active' AND activation_closure = 'complete' "
            "AND state_version = 3) OR "
            "(state IN ('ended','expired','revoked') AND started_at IS NULL "
            "AND activation_closure = 'pending' AND state_version = 2) OR "
            "(state IN ('ended','expired','revoked') AND started_at IS NULL "
            "AND activation_closure = 'complete' AND state_version = 3) OR "
            "(state IN ('ended','expired','revoked') AND started_at IS NOT NULL "
            "AND activation_closure = 'pending' AND state_version = 3) OR "
            "(state IN ('ended','expired','revoked') AND started_at IS NOT NULL "
            "AND activation_closure = 'complete' AND state_version = 4)",
            name="ck_development_sessions_version_shape",
        ),
        sa.ForeignKeyConstraint(
            ["begin_operation_id"],
            ["operations.operation_id"],
            name="fk_development_sessions_begin_operation",
        ),
        sa.ForeignKeyConstraint(
            ["controller_id", "controller_epoch"],
            ["controller_owners.controller_id", "controller_owners.controller_epoch"],
            name="fk_development_sessions_controller_owner",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["registered_workspaces.workspace_id"],
            name="fk_development_sessions_registered_workspace",
        ),
        sa.PrimaryKeyConstraint("session_id", name="pk_development_sessions"),
        sa.UniqueConstraint("begin_operation_id", name="uq_development_sessions_begin_operation"),
    )
    op.create_index(
        "uq_development_sessions_live_slot",
        "development_sessions",
        ["device_id", "device_epoch", "workspace_id"],
        unique=True,
        sqlite_where=sa.text("state IN ('pending','active')"),
    )
    op.create_table(
        "workspace_operations",
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("session_id", sa.String(length=160), nullable=False),
        sa.Column("workspace_id", sa.String(length=160), nullable=False),
        sa.Column("mutation_kind", sa.String(length=16), nullable=False),
        sa.Column("object_kind", sa.String(length=16), nullable=False),
        sa.Column("source_path_sha256", sa.String(length=64), nullable=True),
        sa.Column("target_path_sha256", sa.String(length=64), nullable=True),
        sa.Column("expected_object_sha256", sa.String(length=64), nullable=True),
        sa.Column("expected_content_sha256", sa.String(length=64), nullable=True),
        sa.Column("expected_link_count", sa.Integer(), nullable=True),
        sa.Column("expected_mount_identity_sha256", sa.String(length=64), nullable=False),
        sa.Column("proposed_content_sha256", sa.String(length=64), nullable=True),
        sa.Column("proposed_byte_count", sa.Integer(), nullable=True),
        sa.Column("state_binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("staging_reference", sa.String(length=512), nullable=True),
        sa.Column("staging_reference_sha256", sa.String(length=64), nullable=True),
        sa.Column("primitive_profile_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "mutation_kind IN ('create','write','patch','move','delete')",
            name="ck_workspace_operations_kind",
        ),
        sa.CheckConstraint(
            "object_kind IN ('regular_file','directory')",
            name="ck_workspace_operations_object_kind",
        ),
        sa.CheckConstraint(
            "mutation_kind NOT IN ('write','patch') OR object_kind = 'regular_file'",
            name="ck_workspace_operations_kind_object",
        ),
        sa.CheckConstraint(
            "length(operation_id) >= 1 AND length(operation_id) <= 160 "
            "AND length(session_id) >= 1 AND length(session_id) <= 160 "
            "AND length(workspace_id) >= 1 AND length(workspace_id) <= 160 "
            "AND length(primitive_profile_version) >= 1 "
            "AND length(primitive_profile_version) <= 64",
            name="ck_workspace_operations_identifiers",
        ),
        sa.CheckConstraint(
            "(mutation_kind = 'create' AND source_path_sha256 IS NULL "
            "AND target_path_sha256 IS NOT NULL) OR "
            "(mutation_kind IN ('write','patch','delete') "
            "AND source_path_sha256 IS NOT NULL AND target_path_sha256 IS NULL) OR "
            "(mutation_kind = 'move' AND source_path_sha256 IS NOT NULL "
            "AND target_path_sha256 IS NOT NULL)",
            name="ck_workspace_operations_path_shape",
        ),
        sa.CheckConstraint(
            "(mutation_kind = 'create' AND expected_object_sha256 IS NULL "
            "AND expected_content_sha256 IS NULL AND expected_link_count IS NULL) OR "
            "(mutation_kind != 'create' AND expected_object_sha256 IS NOT NULL)",
            name="ck_workspace_operations_expected_object",
        ),
        sa.CheckConstraint(
            "(object_kind = 'regular_file' AND mutation_kind != 'create' "
            "AND expected_content_sha256 IS NOT NULL AND expected_link_count = 1) OR "
            "(object_kind = 'directory' AND expected_content_sha256 IS NULL "
            "AND expected_link_count IS NULL) OR mutation_kind = 'create'",
            name="ck_workspace_operations_existing_object",
        ),
        sa.CheckConstraint(
            "(mutation_kind IN ('write','patch') AND proposed_content_sha256 IS NOT NULL "
            "AND proposed_byte_count IS NOT NULL AND proposed_byte_count >= 0 "
            "AND proposed_byte_count <= 4194304) OR "
            "(mutation_kind = 'create' AND object_kind = 'regular_file' "
            "AND proposed_content_sha256 IS NOT NULL AND proposed_byte_count IS NOT NULL "
            "AND proposed_byte_count >= 0 AND proposed_byte_count <= 4194304) OR "
            "(mutation_kind = 'create' AND object_kind = 'directory' "
            "AND proposed_content_sha256 IS NULL AND proposed_byte_count IS NULL) OR "
            "(mutation_kind IN ('move','delete') AND proposed_content_sha256 IS NULL "
            "AND proposed_byte_count IS NULL)",
            name="ck_workspace_operations_proposed_content",
        ),
        sa.CheckConstraint(
            "length(expected_mount_identity_sha256) = 64 "
            "AND length(state_binding_sha256) = 64 "
            "AND (source_path_sha256 IS NULL OR length(source_path_sha256) = 64) "
            "AND (target_path_sha256 IS NULL OR length(target_path_sha256) = 64) "
            "AND (expected_object_sha256 IS NULL OR length(expected_object_sha256) = 64) "
            "AND (expected_content_sha256 IS NULL OR length(expected_content_sha256) = 64) "
            "AND (proposed_content_sha256 IS NULL OR length(proposed_content_sha256) = 64) "
            "AND (staging_reference_sha256 IS NULL OR length(staging_reference_sha256) = 64)",
            name="ck_workspace_operations_digests",
        ),
        sa.CheckConstraint(
            "((mutation_kind IN ('write','patch') OR "
            "(mutation_kind = 'create' AND object_kind = 'regular_file')) "
            "AND staging_reference IS NOT NULL AND staging_reference_sha256 IS NOT NULL "
            "AND length(staging_reference) >= 1 AND length(staging_reference) <= 512) OR "
            "((mutation_kind IN ('move','delete') OR "
            "(mutation_kind = 'create' AND object_kind = 'directory')) "
            "AND staging_reference IS NULL AND staging_reference_sha256 IS NULL)",
            name="ck_workspace_operations_staging_reference",
        ),
        sa.CheckConstraint("updated_at >= created_at", name="ck_workspace_operations_time_order"),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.operation_id"],
            name="fk_workspace_operations_operation",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["development_sessions.session_id"],
            name="fk_workspace_operations_session",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["registered_workspaces.workspace_id"],
            name="fk_workspace_operations_registered_workspace",
        ),
        sa.PrimaryKeyConstraint("operation_id", name="pk_workspace_operations"),
    )
    op.create_index(
        "ix_workspace_operations_session",
        "workspace_operations",
        ["session_id", "created_at"],
    )
    op.create_table(
        "workspace_mutation_fences",
        sa.Column("workspace_id", sa.String(length=160), nullable=False),
        sa.Column("fence_version", sa.Integer(), nullable=False),
        sa.Column("active_operation_id", sa.String(length=160), nullable=True),
        sa.Column("active_contract", sa.String(length=160), nullable=True),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("fence_version >= 1", name="ck_workspace_fences_version"),
        sa.CheckConstraint(
            "length(workspace_id) >= 1 AND length(workspace_id) <= 160 "
            "AND (active_operation_id IS NULL OR "
            "(length(active_operation_id) >= 1 AND length(active_operation_id) <= 160)) "
            "AND (active_contract IS NULL OR "
            "(length(active_contract) >= 1 AND length(active_contract) <= 160))",
            name="ck_workspace_fences_identifiers",
        ),
        sa.CheckConstraint(
            "(active_operation_id IS NULL AND active_contract IS NULL "
            "AND acquired_at IS NULL) OR "
            "(active_operation_id IS NOT NULL AND active_contract IS NOT NULL "
            "AND acquired_at IS NOT NULL)",
            name="ck_workspace_fences_owner_shape",
        ),
        sa.CheckConstraint(
            "acquired_at IS NULL OR updated_at >= acquired_at",
            name="ck_workspace_fences_time_order",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["registered_workspaces.workspace_id"],
            name="fk_workspace_fences_registered_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["active_operation_id"],
            ["operations.operation_id"],
            name="fk_workspace_fences_active_operation",
        ),
        sa.PrimaryKeyConstraint("workspace_id", name="pk_workspace_mutation_fences"),
        sa.UniqueConstraint("active_operation_id", name="uq_workspace_fences_active_operation"),
    )
    op.execute(
        """
        CREATE TRIGGER trg_registered_workspace_identity_immutable
        BEFORE UPDATE ON registered_workspaces
        WHEN NEW.workspace_id IS NOT OLD.workspace_id OR
             NEW.profile_sha256 IS NOT OLD.profile_sha256 OR
             NEW.root_identity_sha256 IS NOT OLD.root_identity_sha256 OR
             NEW.mount_identity_sha256 IS NOT OLD.mount_identity_sha256 OR
             NEW.root_device IS NOT OLD.root_device OR
             NEW.root_inode IS NOT OLD.root_inode OR
             NEW.mount_id IS NOT OLD.mount_id OR
             NEW.mount_device IS NOT OLD.mount_device OR
             NEW.filesystem_type IS NOT OLD.filesystem_type OR
             NEW.owner_uid IS NOT OLD.owner_uid OR
             NEW.owner_gid IS NOT OLD.owner_gid OR
             NEW.mode IS NOT OLD.mode OR
             NEW.primitive_profile_version IS NOT OLD.primitive_profile_version OR
             NEW.registration_version IS NOT OLD.registration_version OR
             NEW.registered_at IS NOT OLD.registered_at
        BEGIN
            SELECT RAISE(ABORT, 'registered workspace identity is immutable');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_terminal_development_session_immutable
        BEFORE UPDATE ON development_sessions
        WHEN OLD.state IN ('ended','expired','revoked') AND (
             NEW.session_id IS NOT OLD.session_id OR
             NEW.begin_operation_id IS NOT OLD.begin_operation_id OR
             NEW.state IS NOT OLD.state OR
             NEW.controller_id IS NOT OLD.controller_id OR
             NEW.controller_epoch IS NOT OLD.controller_epoch OR
             NEW.device_id IS NOT OLD.device_id OR
             NEW.device_epoch IS NOT OLD.device_epoch OR
             NEW.workspace_id IS NOT OLD.workspace_id OR
             NEW.workspace_profile_sha256 IS NOT OLD.workspace_profile_sha256 OR
             NEW.workspace_root_identity_sha256 IS NOT OLD.workspace_root_identity_sha256 OR
             NEW.workspace_mount_identity_sha256 IS NOT OLD.workspace_mount_identity_sha256 OR
             NEW.policy_version IS NOT OLD.policy_version OR
             NEW.contract_profile_sha256 IS NOT OLD.contract_profile_sha256 OR
             NEW.objective_sha256 IS NOT OLD.objective_sha256 OR
             NEW.created_at IS NOT OLD.created_at OR
             NEW.expires_at IS NOT OLD.expires_at OR
             NEW.trusted_time_generation IS NOT OLD.trusted_time_generation OR
             NEW.activation_boot_id_digest IS NOT OLD.activation_boot_id_digest OR
             NEW.monotonic_deadline_ns IS NOT OLD.monotonic_deadline_ns OR
             NEW.started_at IS NOT OLD.started_at OR
             NEW.terminal_at IS NOT OLD.terminal_at OR
             NEW.terminal_reason IS NOT OLD.terminal_reason OR
             NEW.activation_effect_reference IS NOT OLD.activation_effect_reference OR
             NEW.activation_effect_reference_sha256
                 IS NOT OLD.activation_effect_reference_sha256 OR
             OLD.activation_closure != 'pending' OR
             NEW.activation_closure != 'complete' OR
             NEW.activation_closure_version != OLD.activation_closure_version + 1 OR
             NEW.state_version != OLD.state_version + 1 OR
             NEW.updated_at < OLD.updated_at
        )
        BEGIN
            SELECT RAISE(ABORT, 'terminal development session authority is immutable');
        END
        """
    )
    op.execute("UPDATE kernel_meta SET schema_generation = 3, updated_at = CURRENT_TIMESTAMP")


def downgrade() -> None:
    op.execute("UPDATE kernel_meta SET schema_generation = 2, updated_at = CURRENT_TIMESTAMP")
    op.execute("DROP TRIGGER IF EXISTS trg_terminal_development_session_immutable")
    op.execute("DROP TRIGGER IF EXISTS trg_registered_workspace_identity_immutable")
    op.drop_table("workspace_mutation_fences")
    op.drop_index("ix_workspace_operations_session", table_name="workspace_operations")
    op.drop_table("workspace_operations")
    op.drop_index("uq_development_sessions_live_slot", table_name="development_sessions")
    op.drop_table("development_sessions")
    op.drop_table("registered_workspaces")
