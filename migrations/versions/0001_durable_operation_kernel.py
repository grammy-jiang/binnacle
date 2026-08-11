"""Create the durable operation kernel schema.

Revision ID: 0001_durable_operation_kernel
Revises: None

This migration intentionally declares its complete historical schema.  It must
not import live ORM metadata: later model changes belong in later revisions.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0001_durable_operation_kernel"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names()) - {"alembic_version"}
    if existing:
        raise RuntimeError("refusing to adopt an unmanaged non-empty database")

    op.create_table(
        "controller_owners",
        sa.Column("controller_id", sa.String(length=160), nullable=False),
        sa.Column("controller_epoch", sa.Integer(), nullable=False),
        sa.Column("controller_profile_id", sa.String(length=160), nullable=False),
        sa.Column("controller_profile_version", sa.String(length=64), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.CheckConstraint("controller_epoch >= 1", name="ck_controller_owner_epoch"),
        sa.PrimaryKeyConstraint("controller_id", "controller_epoch", name="pk_controller_owners"),
    )
    op.create_table(
        "kernel_meta",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("schema_generation", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=160), nullable=False),
        sa.Column("device_epoch", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("audit_stream_id", sa.String(length=160), nullable=False),
        sa.Column("audit_epoch", sa.String(length=160), nullable=False),
        sa.Column("audit_epoch_generation", sa.Integer(), nullable=False),
        sa.Column("audit_last_sequence", sa.Integer(), nullable=False),
        sa.Column("audit_last_hash", sa.String(length=64), nullable=True),
        sa.Column("audit_failure_generation", sa.Integer(), nullable=False),
        sa.Column("audit_failure_latched", sa.Boolean(), nullable=False),
        sa.Column("audit_failure_reason_code", sa.String(length=160), nullable=True),
        sa.Column("audit_failure_detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("audit_recovered_generation", sa.Integer(), nullable=False),
        sa.Column("audit_recovery_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "trusted_wall_time_high_watermark",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("trusted_time_boot_id_digest", sa.String(length=64), nullable=True),
        sa.Column("trusted_time_monotonic_ns", sa.Integer(), nullable=True),
        sa.Column("trusted_time_generation", sa.Integer(), nullable=False),
        sa.Column("consequential_admission_enabled", sa.Boolean(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_kernel_meta_singleton"),
        sa.CheckConstraint("schema_generation >= 1", name="ck_kernel_meta_schema_generation"),
        sa.CheckConstraint("device_epoch >= 1", name="ck_kernel_meta_device_epoch"),
        sa.CheckConstraint(
            "audit_epoch_generation >= 1", name="ck_kernel_meta_audit_epoch_generation"
        ),
        sa.CheckConstraint("audit_last_sequence >= 0", name="ck_kernel_meta_audit_sequence"),
        sa.CheckConstraint(
            "audit_failure_generation >= 0", name="ck_kernel_meta_failure_generation"
        ),
        sa.CheckConstraint(
            "audit_recovered_generation >= 0",
            name="ck_kernel_meta_recovered_generation",
        ),
        sa.CheckConstraint(
            "audit_recovered_generation <= audit_failure_generation",
            name="ck_kernel_meta_recovery_order",
        ),
        sa.CheckConstraint(
            "(audit_failure_latched = 1 AND audit_failure_generation > "
            "audit_recovered_generation AND audit_failure_reason_code IS NOT NULL AND "
            "audit_failure_detected_at IS NOT NULL) OR (audit_failure_latched = 0 AND "
            "audit_failure_reason_code IS NULL AND audit_failure_detected_at IS NULL)",
            name="ck_kernel_meta_failure_latch",
        ),
        sa.CheckConstraint(
            "audit_recovered_generation = 0 OR audit_recovery_evidence_sha256 IS NOT NULL",
            name="ck_kernel_meta_recovery_evidence",
        ),
        sa.CheckConstraint("trusted_time_generation >= 1", name="ck_kernel_meta_time_generation"),
        sa.CheckConstraint(
            "trusted_time_monotonic_ns IS NULL OR trusted_time_monotonic_ns >= 0",
            name="ck_kernel_meta_time_monotonic",
        ),
        sa.CheckConstraint(
            "consequential_admission_enabled = 0 OR "
            "(audit_failure_latched = 0 AND "
            "audit_failure_generation = audit_recovered_generation)",
            name="ck_kernel_meta_admission_safe",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_kernel_meta"),
    )
    op.create_table(
        "operations",
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("controller_id", sa.String(length=160), nullable=False),
        sa.Column("controller_epoch", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=160), nullable=False),
        sa.Column("device_epoch", sa.Integer(), nullable=False),
        sa.Column("operation_contract", sa.String(length=160), nullable=False),
        sa.Column("operation_contract_version", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=True),
        sa.Column("tool_contract_version", sa.String(length=64), nullable=True),
        sa.Column("request_fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("effect_knowledge", sa.String(length=32), nullable=False),
        sa.Column("terminality", sa.String(length=40), nullable=False),
        sa.Column("automatic_retry_allowed", sa.Boolean(), nullable=False),
        sa.Column("effect_boundary_crossed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effect_reference", sa.String(length=512), nullable=True),
        sa.Column("effect_reference_digest", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=160), nullable=True),
        sa.Column("error_summary", sa.String(length=512), nullable=True),
        sa.Column("retry_action", sa.String(length=64), nullable=True),
        sa.Column("runtime_build_sha256", sa.String(length=64), nullable=False),
        sa.Column("runtime_config_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "controller_profile_version_snapshot",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorised_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("device_epoch >= 1", name="ck_operations_device_epoch"),
        sa.CheckConstraint("state_version >= 1", name="ck_operations_state_version"),
        sa.CheckConstraint(
            "state IN ('received','rejected','authorised','running','paused','cancelling',"
            "'cancelled','succeeded','failed','uncertain')",
            name="ck_operations_state",
        ),
        sa.CheckConstraint(
            "effect_knowledge IN ('none','known_no_effect','known_effect','partial','uncertain')",
            name="ck_operations_effect_knowledge",
        ),
        sa.CheckConstraint(
            "terminality IN ('non_terminal','effect_terminal_reconcilable','terminal')",
            name="ck_operations_terminality",
        ),
        sa.CheckConstraint("automatic_retry_allowed = 0", name="ck_operations_no_auto_retry"),
        sa.ForeignKeyConstraint(
            ["controller_id", "controller_epoch"],
            ["controller_owners.controller_id", "controller_owners.controller_epoch"],
            name="fk_operations_controller_owner",
        ),
        sa.PrimaryKeyConstraint("operation_id", name="pk_operations"),
    )
    op.create_index("ix_operations_state", "operations", ["state", "updated_at"])
    op.create_table(
        "idempotency_bindings",
        sa.Column("binding_id", sa.String(length=160), nullable=False),
        sa.Column("device_id", sa.String(length=160), nullable=False),
        sa.Column("device_epoch", sa.Integer(), nullable=False),
        sa.Column("key_mode", sa.String(length=40), nullable=False),
        sa.Column("key_digest_sha256", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("contract_version", sa.String(length=64), nullable=False),
        sa.Column("owner_controller_id", sa.String(length=160), nullable=True),
        sa.Column("owner_controller_epoch", sa.Integer(), nullable=True),
        sa.Column("owner_controller_digest", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("prepared_operation_id", sa.String(length=160), nullable=True),
        sa.Column("prepared_input_sha256", sa.String(length=64), nullable=True),
        sa.Column("prepared_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prepared_state_binding_sha256", sa.String(length=64), nullable=True),
        sa.Column("prepared_registered_boot_id_digest", sa.String(length=64), nullable=True),
        sa.Column("prepared_monotonic_deadline_ns", sa.Integer(), nullable=True),
        sa.Column("target_identity_sha256", sa.String(length=64), nullable=True),
        sa.Column("maximum_effect_sha256", sa.String(length=64), nullable=True),
        sa.Column("operation_id", sa.String(length=160), nullable=True),
        sa.Column("terminal_class", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_access_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_kind", sa.String(length=16), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("conflict_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("device_epoch >= 1", name="ck_bindings_device_epoch"),
        sa.CheckConstraint(
            "key_mode IN ('caller_key','prepared_execution_nonce','derived_member_key')",
            name="ck_bindings_key_mode",
        ),
        sa.CheckConstraint("record_kind IN ('full','tombstone')", name="ck_bindings_record_kind"),
        sa.CheckConstraint(
            "duplicate_count >= 0 AND conflict_count >= 0", name="ck_bindings_counts"
        ),
        sa.CheckConstraint(
            "(record_kind = 'full' AND owner_controller_id IS NOT NULL AND "
            "owner_controller_epoch IS NOT NULL) OR (record_kind = 'tombstone' AND "
            "owner_controller_id IS NULL AND owner_controller_epoch IS NULL)",
            name="ck_bindings_owner_shape",
        ),
        sa.CheckConstraint(
            "(record_kind = 'tombstone' AND operation_id IS NULL AND retired_at IS NOT "
            "NULL AND terminal_class IS NOT NULL AND owner_controller_id IS NULL AND "
            "owner_controller_epoch IS NULL AND prepared_operation_id IS NULL AND "
            "prepared_input_sha256 IS NULL AND prepared_expires_at IS NULL AND "
            "prepared_state_binding_sha256 IS NULL AND "
            "prepared_registered_boot_id_digest IS NULL AND "
            "prepared_monotonic_deadline_ns IS NULL) OR record_kind = 'full'",
            name="ck_bindings_tombstone_shape",
        ),
        sa.CheckConstraint(
            "(record_kind = 'full' AND key_mode = 'prepared_execution_nonce' AND "
            "prepared_operation_id IS NOT NULL AND prepared_input_sha256 IS NOT NULL "
            "AND prepared_expires_at IS NOT NULL AND prepared_state_binding_sha256 IS "
            "NOT NULL AND prepared_registered_boot_id_digest IS NOT NULL AND "
            "prepared_monotonic_deadline_ns IS NOT NULL) OR (record_kind = 'full' AND "
            "key_mode != 'prepared_execution_nonce' AND operation_id IS NOT NULL AND "
            "prepared_operation_id IS NULL AND prepared_input_sha256 IS NULL AND "
            "prepared_expires_at IS NULL AND prepared_state_binding_sha256 IS NULL AND "
            "prepared_registered_boot_id_digest IS NULL AND "
            "prepared_monotonic_deadline_ns IS NULL) OR record_kind = 'tombstone'",
            name="ck_bindings_full_shape",
        ),
        sa.CheckConstraint(
            "operation_id IS NOT NULL OR (record_kind = 'full' AND "
            "key_mode = 'prepared_execution_nonce') OR record_kind = 'tombstone'",
            name="ck_bindings_operation_reference",
        ),
        sa.ForeignKeyConstraint(
            ["owner_controller_id", "owner_controller_epoch"],
            ["controller_owners.controller_id", "controller_owners.controller_epoch"],
            name="fk_bindings_controller_owner",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.operation_id"],
            name="fk_bindings_operation",
        ),
        sa.PrimaryKeyConstraint("binding_id", name="pk_idempotency_bindings"),
        sa.UniqueConstraint(
            "device_id",
            "device_epoch",
            "tool_name",
            "contract_version",
            "key_digest_sha256",
            name="uq_idempotency_global_scope",
        ),
    )
    op.create_index("ix_bindings_operation", "idempotency_bindings", ["operation_id"])
    op.create_table(
        "operation_transitions",
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("from_state", sa.String(length=32), nullable=True),
        sa.Column("to_state", sa.String(length=32), nullable=False),
        sa.Column("effect_knowledge", sa.String(length=32), nullable=False),
        sa.Column("terminality", sa.String(length=40), nullable=False),
        sa.Column("reason_code", sa.String(length=160), nullable=False),
        sa.Column("error_code", sa.String(length=160), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("runtime_build_sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint("state_version >= 1", name="ck_operation_transitions_version"),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.operation_id"],
            name="fk_transitions_operation",
        ),
        sa.PrimaryKeyConstraint("operation_id", "state_version", name="pk_operation_transitions"),
    )
    op.create_table(
        "payload_objects",
        sa.Column("payload_id", sa.String(length=160), nullable=False),
        sa.Column("operation_id", sa.String(length=160), nullable=True),
        sa.Column("controller_id", sa.String(length=160), nullable=False),
        sa.Column("controller_epoch", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("lifecycle", sa.String(length=16), nullable=False),
        sa.Column("relative_path", sa.String(length=512), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("encoding", sa.String(length=64), nullable=False),
        sa.Column("decoded_byte_count", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("information_class", sa.String(length=32), nullable=False),
        sa.Column("retention_class", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_access_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('result','stdout','stderr','evidence','internal')",
            name="ck_payload_kind",
        ),
        sa.CheckConstraint(
            "lifecycle IN ('building','complete','failed','expired','deleted')",
            name="ck_payload_lifecycle",
        ),
        sa.CheckConstraint("decoded_byte_count >= 0", name="ck_payload_bytes"),
        sa.CheckConstraint(
            "lifecycle != 'complete' OR (sha256 IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_payload_complete",
        ),
        sa.ForeignKeyConstraint(
            ["controller_id", "controller_epoch"],
            ["controller_owners.controller_id", "controller_owners.controller_epoch"],
            name="fk_payload_controller_owner",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.operation_id"],
            name="fk_payload_operation",
        ),
        sa.PrimaryKeyConstraint("payload_id", name="pk_payload_objects"),
        sa.UniqueConstraint("relative_path", name="uq_payload_relative_path"),
    )
    op.create_index("ix_payload_owner", "payload_objects", ["controller_id", "controller_epoch"])
    op.create_table(
        "policy_decisions",
        sa.Column("policy_decision_id", sa.String(length=160), nullable=False),
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("policy_id", sa.String(length=160), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("controller_id", sa.String(length=160), nullable=False),
        sa.Column("controller_epoch", sa.Integer(), nullable=False),
        sa.Column("operation_contract", sa.String(length=160), nullable=False),
        sa.Column("operation_contract_version", sa.String(length=64), nullable=False),
        sa.Column("required_scope_digest", sa.String(length=64), nullable=True),
        sa.Column("normalized_target_digest", sa.String(length=64), nullable=True),
        sa.Column("input_facts_sha256", sa.String(length=64), nullable=False),
        sa.Column("reason_codes_json", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("runtime_policy_sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint("decision IN ('allow','deny')", name="ck_policy_decisions_value"),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.operation_id"],
            name="fk_policy_decisions_operation",
        ),
        sa.PrimaryKeyConstraint("policy_decision_id", name="pk_policy_decisions"),
        sa.UniqueConstraint("operation_id", name="uq_policy_decisions_operation"),
    )
    op.create_table(
        "operation_evidence",
        sa.Column("evidence_id", sa.String(length=160), nullable=False),
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("provenance", sa.String(length=64), nullable=False),
        sa.Column("information_class", sa.String(length=32), nullable=False),
        sa.Column("fresh_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_sha256", sa.String(length=64), nullable=True),
        sa.Column("payload_id", sa.String(length=160), nullable=True),
        sa.Column("audit_ref", sa.String(length=160), nullable=True),
        sa.Column("facts_json", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.operation_id"],
            name="fk_evidence_operation",
        ),
        sa.ForeignKeyConstraint(
            ["payload_id"],
            ["payload_objects.payload_id"],
            name="fk_evidence_payload",
        ),
        sa.PrimaryKeyConstraint("evidence_id", name="pk_operation_evidence"),
    )


def downgrade() -> None:
    op.drop_table("operation_evidence")
    op.drop_table("policy_decisions")
    op.drop_index("ix_payload_owner", table_name="payload_objects")
    op.drop_table("payload_objects")
    op.drop_table("operation_transitions")
    op.drop_index("ix_bindings_operation", table_name="idempotency_bindings")
    op.drop_table("idempotency_bindings")
    op.drop_index("ix_operations_state", table_name="operations")
    op.drop_table("operations")
    op.drop_table("kernel_meta")
    op.drop_table("controller_owners")
