"""SQLAlchemy models for migration 0001 durable operation kernel."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class KernelMetaModel(Base):
    __tablename__ = "kernel_meta"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_kernel_meta_singleton"),
        CheckConstraint("schema_generation >= 1", name="ck_kernel_meta_schema_generation"),
        CheckConstraint("device_epoch >= 1", name="ck_kernel_meta_device_epoch"),
        CheckConstraint(
            "audit_epoch_generation >= 1", name="ck_kernel_meta_audit_epoch_generation"
        ),
        CheckConstraint("audit_last_sequence >= 0", name="ck_kernel_meta_audit_sequence"),
        CheckConstraint("audit_failure_generation >= 0", name="ck_kernel_meta_failure_generation"),
        CheckConstraint(
            "audit_recovered_generation >= 0", name="ck_kernel_meta_recovered_generation"
        ),
        CheckConstraint(
            "audit_recovered_generation <= audit_failure_generation",
            name="ck_kernel_meta_recovery_order",
        ),
        CheckConstraint(
            "(audit_failure_latched = 1 AND audit_failure_generation > audit_recovered_generation "
            "AND audit_failure_reason_code IS NOT NULL AND audit_failure_detected_at IS NOT NULL) "
            "OR (audit_failure_latched = 0 AND audit_failure_reason_code IS NULL "
            "AND audit_failure_detected_at IS NULL)",
            name="ck_kernel_meta_failure_latch",
        ),
        CheckConstraint(
            "audit_recovered_generation = 0 OR audit_recovery_evidence_sha256 IS NOT NULL",
            name="ck_kernel_meta_recovery_evidence",
        ),
        CheckConstraint("trusted_time_generation >= 1", name="ck_kernel_meta_time_generation"),
        CheckConstraint(
            "trusted_time_monotonic_ns IS NULL OR trusted_time_monotonic_ns >= 0",
            name="ck_kernel_meta_time_monotonic",
        ),
        CheckConstraint(
            "consequential_admission_enabled = 0 OR "
            "(audit_failure_latched = 0 AND "
            "audit_failure_generation = audit_recovered_generation)",
            name="ck_kernel_meta_admission_safe",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schema_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    device_id: Mapped[str] = mapped_column(String(160), nullable=False)
    device_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    audit_stream_id: Mapped[str] = mapped_column(String(160), nullable=False)
    audit_epoch: Mapped[str] = mapped_column(String(160), nullable=False)
    audit_epoch_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    audit_last_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    audit_last_hash: Mapped[str | None] = mapped_column(String(64))
    audit_failure_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    audit_failure_latched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    audit_failure_reason_code: Mapped[str | None] = mapped_column(String(160))
    audit_failure_detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audit_recovered_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    audit_recovery_evidence_sha256: Mapped[str | None] = mapped_column(String(64))
    trusted_wall_time_high_watermark: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    trusted_time_boot_id_digest: Mapped[str | None] = mapped_column(String(64))
    trusted_time_monotonic_ns: Mapped[int | None] = mapped_column(Integer)
    trusted_time_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    consequential_admission_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )


class ControllerOwnerModel(Base):
    __tablename__ = "controller_owners"
    __table_args__ = (CheckConstraint("controller_epoch >= 1", name="ck_controller_owner_epoch"),)

    controller_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    controller_epoch: Mapped[int] = mapped_column(Integer, primary_key=True)
    controller_profile_id: Mapped[str] = mapped_column(String(160), nullable=False)
    controller_profile_version: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)


class OperationModel(Base):
    __tablename__ = "operations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["controller_id", "controller_epoch"],
            ["controller_owners.controller_id", "controller_owners.controller_epoch"],
            name="fk_operations_controller_owner",
        ),
        CheckConstraint("device_epoch >= 1", name="ck_operations_device_epoch"),
        CheckConstraint("state_version >= 1", name="ck_operations_state_version"),
        CheckConstraint(
            "state IN ('received','rejected','authorised','running','paused','cancelling',"
            "'cancelled','succeeded','failed','uncertain')",
            name="ck_operations_state",
        ),
        CheckConstraint(
            "effect_knowledge IN ('none','known_no_effect','known_effect','partial','uncertain')",
            name="ck_operations_effect_knowledge",
        ),
        CheckConstraint(
            "terminality IN ('non_terminal','effect_terminal_reconcilable','terminal')",
            name="ck_operations_terminality",
        ),
        CheckConstraint("automatic_retry_allowed = 0", name="ck_operations_no_auto_retry"),
    )

    operation_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    controller_id: Mapped[str] = mapped_column(String(160), nullable=False)
    controller_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    device_id: Mapped[str] = mapped_column(String(160), nullable=False)
    device_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_contract: Mapped[str] = mapped_column(String(160), nullable=False)
    operation_contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(128))
    tool_contract_version: Mapped[str | None] = mapped_column(String(64))
    request_fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    effect_knowledge: Mapped[str] = mapped_column(String(32), nullable=False)
    terminality: Mapped[str] = mapped_column(String(40), nullable=False)
    automatic_retry_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    effect_boundary_crossed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effect_reference: Mapped[str | None] = mapped_column(String(512))
    effect_reference_digest: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(160))
    error_summary: Mapped[str | None] = mapped_column(String(512))
    retry_action: Mapped[str | None] = mapped_column(String(64))
    runtime_build_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    controller_profile_version_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authorised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationTransitionModel(Base):
    __tablename__ = "operation_transitions"
    __table_args__ = (
        CheckConstraint("state_version >= 1", name="ck_operation_transitions_version"),
        CheckConstraint(
            "(state_version = 1 AND from_state IS NULL AND to_state = 'received') OR "
            "(state_version > 1 AND from_state IS NOT NULL)",
            name="ck_operation_transitions_shape",
        ),
    )

    operation_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("operations.operation_id", name="fk_transitions_operation"),
        primary_key=True,
    )
    state_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_state: Mapped[str | None] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    effect_knowledge: Mapped[str] = mapped_column(String(32), nullable=False)
    terminality: Mapped[str] = mapped_column(String(40), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(160), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(160))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    runtime_build_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class IdempotencyBindingModel(Base):
    __tablename__ = "idempotency_bindings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_controller_id", "owner_controller_epoch"],
            ["controller_owners.controller_id", "controller_owners.controller_epoch"],
            name="fk_bindings_controller_owner",
        ),
        UniqueConstraint(
            "device_id",
            "device_epoch",
            "tool_name",
            "contract_version",
            "key_digest_sha256",
            name="uq_idempotency_global_scope",
        ),
        CheckConstraint("device_epoch >= 1", name="ck_bindings_device_epoch"),
        CheckConstraint(
            "key_mode IN ('caller_key','prepared_execution_nonce','derived_member_key')",
            name="ck_bindings_key_mode",
        ),
        CheckConstraint("record_kind IN ('full','tombstone')", name="ck_bindings_record_kind"),
        CheckConstraint("duplicate_count >= 0 AND conflict_count >= 0", name="ck_bindings_counts"),
        CheckConstraint(
            "(record_kind = 'full' AND owner_controller_id IS NOT NULL "
            "AND owner_controller_epoch IS NOT NULL) OR "
            "(record_kind = 'tombstone' AND owner_controller_id IS NULL "
            "AND owner_controller_epoch IS NULL)",
            name="ck_bindings_owner_shape",
        ),
        CheckConstraint(
            "(record_kind = 'tombstone' AND operation_id IS NULL AND retired_at IS NOT NULL "
            "AND terminal_class IS NOT NULL AND owner_controller_id IS NULL "
            "AND owner_controller_epoch IS NULL AND prepared_operation_id IS NULL "
            "AND prepared_input_sha256 IS NULL AND prepared_expires_at IS NULL "
            "AND prepared_state_binding_sha256 IS NULL "
            "AND prepared_registered_boot_id_digest IS NULL "
            "AND prepared_monotonic_deadline_ns IS NULL) OR record_kind = 'full'",
            name="ck_bindings_tombstone_shape",
        ),
        CheckConstraint(
            "(record_kind = 'full' AND key_mode = 'prepared_execution_nonce' "
            "AND prepared_operation_id IS NOT NULL AND prepared_input_sha256 IS NOT NULL "
            "AND prepared_expires_at IS NOT NULL AND prepared_state_binding_sha256 IS NOT NULL "
            "AND prepared_registered_boot_id_digest IS NOT NULL "
            "AND prepared_monotonic_deadline_ns IS NOT NULL) "
            "OR (record_kind = 'full' AND key_mode != 'prepared_execution_nonce' "
            "AND operation_id IS NOT NULL AND prepared_operation_id IS NULL "
            "AND prepared_input_sha256 IS NULL AND prepared_expires_at IS NULL "
            "AND prepared_state_binding_sha256 IS NULL "
            "AND prepared_registered_boot_id_digest IS NULL "
            "AND prepared_monotonic_deadline_ns IS NULL) OR record_kind = 'tombstone'",
            name="ck_bindings_full_shape",
        ),
        CheckConstraint(
            "operation_id IS NOT NULL OR (record_kind = 'full' "
            "AND key_mode = 'prepared_execution_nonce') OR record_kind = 'tombstone'",
            name="ck_bindings_operation_reference",
        ),
    )

    binding_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(160), nullable=False)
    device_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    key_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    key_digest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_controller_id: Mapped[str | None] = mapped_column(String(160))
    owner_controller_epoch: Mapped[int | None] = mapped_column(Integer)
    owner_controller_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    prepared_operation_id: Mapped[str | None] = mapped_column(String(160))
    prepared_input_sha256: Mapped[str | None] = mapped_column(String(64))
    prepared_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prepared_state_binding_sha256: Mapped[str | None] = mapped_column(String(64))
    prepared_registered_boot_id_digest: Mapped[str | None] = mapped_column(String(64))
    prepared_monotonic_deadline_ns: Mapped[int | None] = mapped_column(Integer)
    target_identity_sha256: Mapped[str | None] = mapped_column(String(64))
    maximum_effect_sha256: Mapped[str | None] = mapped_column(String(64))
    operation_id: Mapped[str | None] = mapped_column(
        String(160), ForeignKey("operations.operation_id", name="fk_bindings_operation")
    )
    terminal_class: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_access_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    record_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conflict_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ProbePathLedgerModel(Base):
    __tablename__ = "probe_path_ledger"
    __table_args__ = (
        CheckConstraint("generation_high_water >= 0", name="ck_probe_ledger_generation_high_water"),
        CheckConstraint(
            "terminal_history_count >= 0 AND terminal_history_count <= generation_high_water",
            name="ck_probe_ledger_terminal_count",
        ),
        CheckConstraint("ledger_version >= 1", name="ck_probe_ledger_version"),
        CheckConstraint(
            "length(terminal_history_sha256) = 64", name="ck_probe_ledger_history_digest"
        ),
        CheckConstraint(
            "(active_artifact_id IS NULL AND active_generation IS NULL AND "
            "active_create_operation_id IS NULL AND terminal_history_count = "
            "generation_high_water) OR (active_artifact_id IS NOT NULL AND "
            "active_generation IS NOT NULL AND active_create_operation_id IS NOT NULL AND "
            "active_generation = generation_high_water AND "
            "terminal_history_count = active_generation - 1)",
            name="ck_probe_ledger_active_shape",
        ),
        ForeignKeyConstraint(
            ["active_artifact_id"],
            ["probe_artifacts.artifact_id"],
            name="fk_probe_ledger_active_artifact",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint("active_artifact_id", name="uq_probe_ledger_active_artifact"),
    )

    relative_path: Mapped[str] = mapped_column(String(255), primary_key=True)
    generation_high_water: Mapped[int] = mapped_column(Integer, nullable=False)
    terminal_history_count: Mapped[int] = mapped_column(Integer, nullable=False)
    terminal_history_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    active_artifact_id: Mapped[str | None] = mapped_column(String(160))
    active_generation: Mapped[int | None] = mapped_column(Integer)
    active_create_operation_id: Mapped[str | None] = mapped_column(
        String(160),
        ForeignKey("operations.operation_id", name="fk_probe_ledger_active_create_operation"),
    )
    ledger_version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProbeArtifactModel(Base):
    __tablename__ = "probe_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["relative_path"],
            ["probe_path_ledger.relative_path"],
            name="fk_probe_artifacts_ledger",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["owner_controller_id", "owner_controller_epoch"],
            ["controller_owners.controller_id", "controller_owners.controller_epoch"],
            name="fk_probe_artifacts_owner",
        ),
        UniqueConstraint(
            "relative_path", "path_generation", name="uq_probe_artifacts_path_generation"
        ),
        UniqueConstraint("create_operation_id", name="uq_probe_artifacts_create_operation"),
        UniqueConstraint("active_cleanup_operation_id", name="uq_probe_artifacts_active_cleanup"),
        UniqueConstraint(
            "removed_by_cleanup_operation_id", name="uq_probe_artifacts_removed_by_cleanup"
        ),
        CheckConstraint("path_generation >= 1", name="ck_probe_artifacts_generation"),
        CheckConstraint("owner_controller_epoch >= 1", name="ck_probe_artifacts_owner_epoch"),
        CheckConstraint("byte_count >= 0 AND byte_count <= 65536", name="ck_probe_artifacts_bytes"),
        CheckConstraint(
            "state IN ('reserved','created','removed','abandoned','uncertain')",
            name="ck_probe_artifacts_state",
        ),
        CheckConstraint(
            "length(content_sha256) = 64 AND "
            "(file_identity_digest IS NULL OR length(file_identity_digest) = 64)",
            name="ck_probe_artifacts_digests",
        ),
        CheckConstraint(
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
    )

    artifact_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    relative_path: Mapped[str] = mapped_column(String(255), nullable=False)
    path_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_controller_id: Mapped[str] = mapped_column(String(160), nullable=False)
    owner_controller_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_count: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    create_operation_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("operations.operation_id", name="fk_probe_artifacts_create_operation"),
        nullable=False,
    )
    active_cleanup_operation_id: Mapped[str | None] = mapped_column(
        String(160),
        ForeignKey("operations.operation_id", name="fk_probe_artifacts_active_cleanup"),
    )
    removed_by_cleanup_operation_id: Mapped[str | None] = mapped_column(
        String(160),
        ForeignKey("operations.operation_id", name="fk_probe_artifacts_removed_by_cleanup"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_identity_digest: Mapped[str | None] = mapped_column(String(64))


class ProbeOperationModel(Base):
    __tablename__ = "probe_operations"
    __table_args__ = (
        CheckConstraint("probe_operation IN ('write','cleanup')", name="ck_probe_operations_kind"),
        CheckConstraint(
            "length(expected_content_sha256) = 64 AND length(prepared_state_binding_sha256) = 64",
            name="ck_probe_operations_digests",
        ),
        CheckConstraint(
            "(probe_operation = 'write' AND expected_byte_count IS NOT NULL AND "
            "expected_byte_count >= 0 AND expected_byte_count <= 65536) OR "
            "(probe_operation = 'cleanup' AND expected_byte_count IS NULL)",
            name="ck_probe_operations_byte_shape",
        ),
        ForeignKeyConstraint(
            ["artifact_id"],
            ["probe_artifacts.artifact_id"],
            name="fk_probe_operations_artifact",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint("prepared_binding_id", name="uq_probe_operations_prepared_binding"),
        UniqueConstraint("caller_binding_id", name="uq_probe_operations_caller_binding"),
    )

    operation_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("operations.operation_id", name="fk_probe_operations_operation"),
        primary_key=True,
    )
    probe_operation: Mapped[str] = mapped_column(String(16), nullable=False)
    prepared_binding_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey(
            "idempotency_bindings.binding_id",
            name="fk_probe_operations_prepared_binding",
        ),
        nullable=False,
    )
    caller_binding_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey(
            "idempotency_bindings.binding_id",
            name="fk_probe_operations_caller_binding",
        ),
        nullable=False,
    )
    artifact_id: Mapped[str] = mapped_column(String(160), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(255), nullable=False)
    expected_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_byte_count: Mapped[int | None] = mapped_column(Integer)
    prepared_state_binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PolicyDecisionModel(Base):
    __tablename__ = "policy_decisions"
    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_policy_decisions_operation"),
        CheckConstraint("decision IN ('allow','deny')", name="ck_policy_decisions_value"),
    )

    policy_decision_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    operation_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("operations.operation_id", name="fk_policy_decisions_operation"),
        nullable=False,
    )
    policy_id: Mapped[str] = mapped_column(String(160), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    controller_id: Mapped[str] = mapped_column(String(160), nullable=False)
    controller_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_contract: Mapped[str] = mapped_column(String(160), nullable=False)
    operation_contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    required_scope_digest: Mapped[str | None] = mapped_column(String(64))
    normalized_target_digest: Mapped[str | None] = mapped_column(String(64))
    input_facts_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_codes_json: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    runtime_policy_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class PayloadObjectModel(Base):
    __tablename__ = "payload_objects"
    __table_args__ = (
        ForeignKeyConstraint(
            ["controller_id", "controller_epoch"],
            ["controller_owners.controller_id", "controller_owners.controller_epoch"],
            name="fk_payload_controller_owner",
        ),
        UniqueConstraint("relative_path", name="uq_payload_relative_path"),
        CheckConstraint(
            "kind IN ('result','stdout','stderr','evidence','internal')",
            name="ck_payload_kind",
        ),
        CheckConstraint(
            "lifecycle IN ('building','complete','failed','expired','deleted')",
            name="ck_payload_lifecycle",
        ),
        CheckConstraint("decoded_byte_count >= 0", name="ck_payload_bytes"),
        CheckConstraint(
            "lifecycle != 'complete' OR (sha256 IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_payload_complete",
        ),
    )

    payload_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    operation_id: Mapped[str | None] = mapped_column(
        String(160), ForeignKey("operations.operation_id", name="fk_payload_operation")
    )
    controller_id: Mapped[str] = mapped_column(String(160), nullable=False)
    controller_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(16), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    encoding: Mapped[str] = mapped_column(String(64), nullable=False)
    decoded_byte_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    information_class: Mapped[str] = mapped_column(String(32), nullable=False)
    retention_class: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_access_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationEvidenceModel(Base):
    __tablename__ = "operation_evidence"

    evidence_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    operation_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("operations.operation_id", name="fk_evidence_operation"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance: Mapped[str] = mapped_column(String(64), nullable=False)
    information_class: Mapped[str] = mapped_column(String(32), nullable=False)
    fresh_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_sha256: Mapped[str | None] = mapped_column(String(64))
    payload_id: Mapped[str | None] = mapped_column(
        String(160), ForeignKey("payload_objects.payload_id", name="fk_evidence_payload")
    )
    audit_ref: Mapped[str | None] = mapped_column(String(160))
    facts_json: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RegisteredWorkspaceModel(Base):
    __tablename__ = "registered_workspaces"
    __table_args__ = (
        CheckConstraint(
            "length(profile_sha256) = 64 AND length(root_identity_sha256) = 64 "
            "AND length(mount_identity_sha256) = 64",
            name="ck_registered_workspaces_digests",
        ),
        CheckConstraint(
            "length(workspace_id) >= 1 AND length(workspace_id) <= 160",
            name="ck_registered_workspaces_identifier",
        ),
        CheckConstraint(
            "root_device >= 0 AND root_inode >= 1 AND mount_id >= 1 AND mount_device >= 0",
            name="ck_registered_workspaces_identity",
        ),
        CheckConstraint(
            "owner_uid >= 0 AND owner_gid >= 0 AND mode >= 0 AND mode <= 4095",
            name="ck_registered_workspaces_ownership",
        ),
        CheckConstraint(
            "length(filesystem_type) >= 1 AND length(filesystem_type) <= 64 "
            "AND length(primitive_profile_version) >= 1 "
            "AND length(primitive_profile_version) <= 64",
            name="ck_registered_workspaces_profile",
        ),
        CheckConstraint("registration_version >= 1", name="ck_registered_workspaces_version"),
        CheckConstraint("updated_at >= registered_at", name="ck_registered_workspaces_time_order"),
        UniqueConstraint("root_identity_sha256", name="uq_registered_workspaces_root_identity"),
    )

    workspace_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    root_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mount_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    root_device: Mapped[int] = mapped_column(Integer, nullable=False)
    root_inode: Mapped[int] = mapped_column(Integer, nullable=False)
    mount_id: Mapped[int] = mapped_column(Integer, nullable=False)
    mount_device: Mapped[int] = mapped_column(Integer, nullable=False)
    filesystem_type: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_uid: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_gid: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[int] = mapped_column(Integer, nullable=False)
    primitive_profile_version: Mapped[str] = mapped_column(String(64), nullable=False)
    registration_version: Mapped[int] = mapped_column(Integer, nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DevelopmentSessionModel(Base):
    __tablename__ = "development_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["controller_id", "controller_epoch"],
            ["controller_owners.controller_id", "controller_owners.controller_epoch"],
            name="fk_development_sessions_controller_owner",
        ),
        CheckConstraint(
            "state IN ('pending','active','ended','expired','revoked')",
            name="ck_development_sessions_state",
        ),
        CheckConstraint(
            "activation_closure IN ('pending','complete')",
            name="ck_development_sessions_activation_closure",
        ),
        CheckConstraint(
            "state_version >= 1 AND activation_closure_version >= 1",
            name="ck_development_sessions_versions",
        ),
        CheckConstraint(
            "length(session_id) >= 1 AND length(session_id) <= 160 "
            "AND length(begin_operation_id) >= 1 AND length(begin_operation_id) <= 160 "
            "AND length(controller_id) >= 1 AND length(controller_id) <= 160 "
            "AND length(device_id) >= 1 AND length(device_id) <= 160 "
            "AND length(workspace_id) >= 1 AND length(workspace_id) <= 160 "
            "AND length(policy_version) >= 1 AND length(policy_version) <= 64",
            name="ck_development_sessions_identifiers",
        ),
        CheckConstraint(
            "controller_epoch >= 1 AND device_epoch >= 1 "
            "AND trusted_time_generation >= 1 AND monotonic_deadline_ns >= 0",
            name="ck_development_sessions_epochs",
        ),
        CheckConstraint(
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
        CheckConstraint(
            "expires_at > created_at AND updated_at >= created_at "
            "AND (started_at IS NULL OR (started_at >= created_at AND started_at < expires_at)) "
            "AND (terminal_at IS NULL OR terminal_at >= created_at) "
            "AND (started_at IS NULL OR updated_at >= started_at) "
            "AND (terminal_at IS NULL OR updated_at >= terminal_at) "
            "AND (started_at IS NULL OR terminal_at IS NULL OR terminal_at >= started_at)",
            name="ck_development_sessions_time_order",
        ),
        CheckConstraint(
            "(activation_effect_reference IS NULL "
            "AND activation_effect_reference_sha256 IS NULL) OR "
            "(activation_effect_reference IS NOT NULL "
            "AND activation_effect_reference_sha256 IS NOT NULL)",
            name="ck_development_sessions_effect_reference",
        ),
        CheckConstraint(
            "((started_at IS NULL AND activation_effect_reference IS NULL) OR "
            "(started_at IS NOT NULL AND activation_effect_reference IS NOT NULL)) "
            "AND (terminal_reason IS NULL OR "
            "(length(terminal_reason) >= 1 AND length(terminal_reason) <= 160)) "
            "AND (activation_effect_reference IS NULL OR "
            "(length(activation_effect_reference) >= 1 "
            "AND length(activation_effect_reference) <= 160))",
            name="ck_development_sessions_history_shape",
        ),
        CheckConstraint(
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
        CheckConstraint(
            "(activation_closure = 'pending' AND activation_closure_version = 1) OR "
            "(activation_closure = 'complete' AND activation_closure_version = 2)",
            name="ck_development_sessions_closure_shape",
        ),
        CheckConstraint(
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
        UniqueConstraint("begin_operation_id", name="uq_development_sessions_begin_operation"),
    )

    session_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    begin_operation_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("operations.operation_id", name="fk_development_sessions_begin_operation"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    activation_closure: Mapped[str] = mapped_column(String(16), nullable=False)
    activation_closure_version: Mapped[int] = mapped_column(Integer, nullable=False)
    controller_id: Mapped[str] = mapped_column(String(160), nullable=False)
    controller_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    device_id: Mapped[str] = mapped_column(String(160), nullable=False)
    device_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    workspace_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey(
            "registered_workspaces.workspace_id",
            name="fk_development_sessions_registered_workspace",
        ),
        nullable=False,
    )
    workspace_profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    workspace_root_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    workspace_mount_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    objective_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trusted_time_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    activation_boot_id_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    monotonic_deadline_ns: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_reason: Mapped[str | None] = mapped_column(String(160))
    activation_effect_reference: Mapped[str | None] = mapped_column(String(160))
    activation_effect_reference_sha256: Mapped[str | None] = mapped_column(String(64))


class WorkspaceOperationModel(Base):
    __tablename__ = "workspace_operations"
    __table_args__ = (
        CheckConstraint(
            "mutation_kind IN ('create','write','patch','move','delete')",
            name="ck_workspace_operations_kind",
        ),
        CheckConstraint(
            "object_kind IN ('regular_file','directory')",
            name="ck_workspace_operations_object_kind",
        ),
        CheckConstraint(
            "mutation_kind NOT IN ('write','patch') OR object_kind = 'regular_file'",
            name="ck_workspace_operations_kind_object",
        ),
        CheckConstraint(
            "length(operation_id) >= 1 AND length(operation_id) <= 160 "
            "AND length(session_id) >= 1 AND length(session_id) <= 160 "
            "AND length(workspace_id) >= 1 AND length(workspace_id) <= 160 "
            "AND length(primitive_profile_version) >= 1 "
            "AND length(primitive_profile_version) <= 64",
            name="ck_workspace_operations_identifiers",
        ),
        CheckConstraint(
            "(mutation_kind = 'create' AND source_path_sha256 IS NULL "
            "AND target_path_sha256 IS NOT NULL) OR "
            "(mutation_kind IN ('write','patch','delete') "
            "AND source_path_sha256 IS NOT NULL AND target_path_sha256 IS NULL) OR "
            "(mutation_kind = 'move' AND source_path_sha256 IS NOT NULL "
            "AND target_path_sha256 IS NOT NULL)",
            name="ck_workspace_operations_path_shape",
        ),
        CheckConstraint(
            "(mutation_kind = 'create' AND expected_object_sha256 IS NULL "
            "AND expected_content_sha256 IS NULL AND expected_link_count IS NULL) OR "
            "(mutation_kind != 'create' AND expected_object_sha256 IS NOT NULL)",
            name="ck_workspace_operations_expected_object",
        ),
        CheckConstraint(
            "(object_kind = 'regular_file' AND mutation_kind != 'create' "
            "AND expected_content_sha256 IS NOT NULL AND expected_link_count = 1) OR "
            "(object_kind = 'directory' AND expected_content_sha256 IS NULL "
            "AND expected_link_count IS NULL) OR mutation_kind = 'create'",
            name="ck_workspace_operations_existing_object",
        ),
        CheckConstraint(
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
        CheckConstraint(
            "length(expected_mount_identity_sha256) = 64 "
            "AND length(state_binding_sha256) = 64 "
            "AND (source_path_sha256 IS NULL OR length(source_path_sha256) = 64) "
            "AND (target_path_sha256 IS NULL OR length(target_path_sha256) = 64) "
            "AND (expected_object_sha256 IS NULL OR length(expected_object_sha256) = 64) "
            "AND (expected_content_sha256 IS NULL OR length(expected_content_sha256) = 64) "
            "AND (proposed_content_sha256 IS NULL OR length(proposed_content_sha256) = 64) "
            "AND (staging_reference_sha256 IS NULL "
            "OR length(staging_reference_sha256) = 64)",
            name="ck_workspace_operations_digests",
        ),
        CheckConstraint(
            "((mutation_kind IN ('write','patch') OR "
            "(mutation_kind = 'create' AND object_kind = 'regular_file')) "
            "AND staging_reference IS NOT NULL AND staging_reference_sha256 IS NOT NULL "
            "AND length(staging_reference) >= 1 AND length(staging_reference) <= 512) OR "
            "((mutation_kind IN ('move','delete') OR "
            "(mutation_kind = 'create' AND object_kind = 'directory')) "
            "AND staging_reference IS NULL AND staging_reference_sha256 IS NULL)",
            name="ck_workspace_operations_staging_reference",
        ),
        CheckConstraint("updated_at >= created_at", name="ck_workspace_operations_time_order"),
    )

    operation_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("operations.operation_id", name="fk_workspace_operations_operation"),
        primary_key=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("development_sessions.session_id", name="fk_workspace_operations_session"),
        nullable=False,
    )
    workspace_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey(
            "registered_workspaces.workspace_id",
            name="fk_workspace_operations_registered_workspace",
        ),
        nullable=False,
    )
    mutation_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    object_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    source_path_sha256: Mapped[str | None] = mapped_column(String(64))
    target_path_sha256: Mapped[str | None] = mapped_column(String(64))
    expected_object_sha256: Mapped[str | None] = mapped_column(String(64))
    expected_content_sha256: Mapped[str | None] = mapped_column(String(64))
    expected_link_count: Mapped[int | None] = mapped_column(Integer)
    expected_mount_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    proposed_content_sha256: Mapped[str | None] = mapped_column(String(64))
    proposed_byte_count: Mapped[int | None] = mapped_column(Integer)
    state_binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    staging_reference: Mapped[str | None] = mapped_column(String(512))
    staging_reference_sha256: Mapped[str | None] = mapped_column(String(64))
    primitive_profile_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkspaceMutationFenceModel(Base):
    __tablename__ = "workspace_mutation_fences"
    __table_args__ = (
        CheckConstraint("fence_version >= 1", name="ck_workspace_fences_version"),
        CheckConstraint(
            "length(workspace_id) >= 1 AND length(workspace_id) <= 160 "
            "AND (active_operation_id IS NULL OR "
            "(length(active_operation_id) >= 1 AND length(active_operation_id) <= 160)) "
            "AND (active_contract IS NULL OR "
            "(length(active_contract) >= 1 AND length(active_contract) <= 160))",
            name="ck_workspace_fences_identifiers",
        ),
        CheckConstraint(
            "(active_operation_id IS NULL AND active_contract IS NULL "
            "AND acquired_at IS NULL) OR "
            "(active_operation_id IS NOT NULL AND active_contract IS NOT NULL "
            "AND acquired_at IS NOT NULL)",
            name="ck_workspace_fences_owner_shape",
        ),
        CheckConstraint(
            "acquired_at IS NULL OR updated_at >= acquired_at",
            name="ck_workspace_fences_time_order",
        ),
        UniqueConstraint("active_operation_id", name="uq_workspace_fences_active_operation"),
    )

    workspace_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey(
            "registered_workspaces.workspace_id",
            name="fk_workspace_fences_registered_workspace",
        ),
        primary_key=True,
    )
    fence_version: Mapped[int] = mapped_column(Integer, nullable=False)
    active_operation_id: Mapped[str | None] = mapped_column(
        String(160),
        ForeignKey("operations.operation_id", name="fk_workspace_fences_active_operation"),
    )
    active_contract: Mapped[str | None] = mapped_column(String(160))
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CommandOperationModel(Base):
    __tablename__ = "command_operations"

    operation_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("operations.operation_id", name="fk_command_operations_operation"),
        primary_key=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("development_sessions.session_id", name="fk_command_operations_session"),
        nullable=False,
    )
    workspace_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("registered_workspaces.workspace_id", name="fk_command_operations_workspace"),
        nullable=False,
    )
    controller_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    device_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    development_session_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    development_session_closure_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ticket_id: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    ticket_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    single_use_nonce_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    ticket_issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ticket_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ticket_boot_id_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    ticket_monotonic_deadline_ns: Mapped[int] = mapped_column(Integer, nullable=False)
    admission_record_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("policy_decisions.policy_decision_id", name="fk_command_operations_admission"),
        nullable=False,
        unique=True,
    )
    command_profile_id: Mapped[str] = mapped_column(String(160), nullable=False)
    workspace_profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    workspace_root_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    workspace_mount_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    workspace_fence_version: Mapped[int] = mapped_column(Integer, nullable=False)
    executable_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    argv_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    cwd_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    environment_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    stdin_sha256: Mapped[str | None] = mapped_column(String(64))
    stdin_reference_sha256: Mapped[str | None] = mapped_column(String(64))
    workspace_script_sha256: Mapped[str | None] = mapped_column(String(64))
    mount_plan_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_plan_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    sandbox_plan_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    process_isolation_plan_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    network_plan_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    record_version: Mapped[int] = mapped_column(Integer, nullable=False)
    acceptance_state: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_id: Mapped[str | None] = mapped_column(String(160), unique=True)
    executor_reference: Mapped[str | None] = mapped_column(String(160))
    accepted_receipt_sha256: Mapped[str | None] = mapped_column(String(64))
    no_accept_reference: Mapped[str | None] = mapped_column(String(160))
    no_accept_receipt_sha256: Mapped[str | None] = mapped_column(String(64))
    phase7_cancel_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    supervisor_ack_cancel_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    supervisor_cancel_disposition: Mapped[str | None] = mapped_column(String(40))
    supervisor_evidence_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    supervisor_cancel_evidence_sha256: Mapped[str | None] = mapped_column(String(64))
    last_executor_state: Mapped[str | None] = mapped_column(String(32))
    terminal_evidence_sha256: Mapped[str | None] = mapped_column(String(64))
    descendants_stopped: Mapped[bool] = mapped_column(Boolean, nullable=False)
    output_finalized: Mapped[bool] = mapped_column(Boolean, nullable=False)
    private_resources_cleaned: Mapped[bool] = mapped_column(Boolean, nullable=False)
    cleanup_evidence_sha256: Mapped[str | None] = mapped_column(String(64))
    closure_state: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CommandCancelRequestModel(Base):
    __tablename__ = "command_cancel_requests"
    __table_args__ = (
        UniqueConstraint(
            "command_operation_id",
            "cancel_generation",
            name="uq_command_cancel_generation",
        ),
    )

    cancel_operation_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("operations.operation_id", name="fk_command_cancel_request_operation"),
        primary_key=True,
    )
    command_operation_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey(
            "command_operations.operation_id",
            name="fk_command_cancel_request_command",
        ),
        nullable=False,
    )
    cancel_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    request_fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GitOperationModel(Base):
    __tablename__ = "git_operations"

    operation_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("operations.operation_id", name="fk_git_operations_operation"),
        primary_key=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("development_sessions.session_id", name="fk_git_operations_session"),
        nullable=False,
    )
    workspace_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("registered_workspaces.workspace_id", name="fk_git_operations_workspace"),
        nullable=False,
    )
    operation_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    repository_profile_id: Mapped[str] = mapped_column(String(96), nullable=False)
    repository_profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    repository_safety_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    repository_state_binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    workspace_fence_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(255))
    destination_ref: Mapped[str | None] = mapped_column(String(255))
    expected_old_oid_algorithm: Mapped[str | None] = mapped_column(String(8))
    expected_old_oid_hex: Mapped[str | None] = mapped_column(String(64))
    desired_oid_algorithm: Mapped[str | None] = mapped_column(String(8))
    desired_oid_hex: Mapped[str | None] = mapped_column(String(64))
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    commit_request_sha256: Mapped[str | None] = mapped_column(String(64))
    remote_request_sha256: Mapped[str | None] = mapped_column(String(64))
    credential_reference_sha256: Mapped[str | None] = mapped_column(String(64))
    current_stage_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    aggregate_effect_knowledge: Mapped[str] = mapped_column(String(24), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GitOperationStageModel(Base):
    __tablename__ = "git_operation_stages"
    __table_args__ = (
        UniqueConstraint("member_id", name="uq_git_stages_member"),
        UniqueConstraint("member_ticket_id", name="uq_git_stages_ticket"),
        UniqueConstraint("execution_id", name="uq_git_stages_execution"),
    )

    operation_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("git_operations.operation_id", name="fk_git_stages_operation"),
        primary_key=True,
    )
    stage_generation: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[str] = mapped_column(String(160), nullable=False)
    stage_kind: Mapped[str] = mapped_column(String(48), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    pre_state_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    member_ticket_id: Mapped[str | None] = mapped_column(String(160))
    member_ticket_sha256: Mapped[str | None] = mapped_column(String(64))
    acceptance_state: Mapped[str] = mapped_column(String(24), nullable=False)
    execution_id: Mapped[str | None] = mapped_column(String(160))
    crossing_state: Mapped[str] = mapped_column(String(24), nullable=False)
    effect_knowledge: Mapped[str] = mapped_column(String(24), nullable=False)
    before_oid_algorithm: Mapped[str | None] = mapped_column(String(8))
    before_oid_hex: Mapped[str | None] = mapped_column(String(64))
    after_oid_algorithm: Mapped[str | None] = mapped_column(String(8))
    after_oid_hex: Mapped[str | None] = mapped_column(String(64))
    cancel_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    acknowledged_cancel_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    executor_evidence_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    cleanup_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    cleanup_evidence_sha256: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GitCommitEvidenceModel(Base):
    __tablename__ = "git_commit_evidence"
    __table_args__ = (
        UniqueConstraint("commit_oid_algorithm", "commit_oid_hex", name="uq_git_commit_oid"),
    )

    operation_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("git_operations.operation_id", name="fk_git_commit_operation"),
        primary_key=True,
    )
    commit_oid_algorithm: Mapped[str] = mapped_column(String(8), nullable=False)
    commit_oid_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    tree_oid_algorithm: Mapped[str] = mapped_column(String(8), nullable=False)
    tree_oid_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_oid_algorithm: Mapped[str] = mapped_column(String(8), nullable=False)
    parent_oid_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    author_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    committer_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    message_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    preimage_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    author_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    committer_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    signer_profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    signer_public_fingerprint: Mapped[str] = mapped_column(String(160), nullable=False)
    signature_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    signature_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    object_imported: Mapped[bool] = mapped_column(Boolean, nullable=False)
    branch_cas_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    main_index_publication_state: Mapped[str] = mapped_column(String(16), nullable=False)
    worktree_evidence_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GitRemoteEvidenceModel(Base):
    __tablename__ = "git_remote_evidence"

    operation_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("git_operations.operation_id", name="fk_git_remote_operation"),
        primary_key=True,
    )
    remote_profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    destination_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    outbound_closure_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    destination_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    expected_oid_algorithm: Mapped[str] = mapped_column(String(8), nullable=False)
    expected_oid_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    desired_oid_algorithm: Mapped[str] = mapped_column(String(8), nullable=False)
    desired_oid_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_oid_algorithm: Mapped[str | None] = mapped_column(String(8))
    observed_oid_hex: Mapped[str | None] = mapped_column(String(64))
    transport_state: Mapped[str] = mapped_column(String(24), nullable=False)
    credential_use_evidence_sha256: Mapped[str | None] = mapped_column(String(64))
    remote_reconciled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    credential_cleanup_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


Index("ix_operations_state", OperationModel.state, OperationModel.updated_at)
Index("ix_bindings_operation", IdempotencyBindingModel.operation_id)
Index("ix_payload_owner", PayloadObjectModel.controller_id, PayloadObjectModel.controller_epoch)
Index(
    "uq_probe_artifacts_live_relative_path",
    ProbeArtifactModel.relative_path,
    unique=True,
    sqlite_where=ProbeArtifactModel.state.in_(("reserved", "created", "uncertain")),
)
Index(
    "uq_development_sessions_live_slot",
    DevelopmentSessionModel.device_id,
    DevelopmentSessionModel.device_epoch,
    DevelopmentSessionModel.workspace_id,
    unique=True,
    sqlite_where=DevelopmentSessionModel.state.in_(("pending", "active")),
)
Index(
    "ix_workspace_operations_session",
    WorkspaceOperationModel.session_id,
    WorkspaceOperationModel.created_at,
)
Index(
    "ix_command_operations_session",
    CommandOperationModel.session_id,
    CommandOperationModel.acceptance_state,
)
Index("ix_git_operations_session", GitOperationModel.session_id, GitOperationModel.state)
Index(
    "uq_git_stages_active_member",
    GitOperationStageModel.operation_id,
    unique=True,
    sqlite_where=GitOperationStageModel.state.in_(
        ("dispatched", "running", "cleanup_pending", "uncertain")
    ),
)
