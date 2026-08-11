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


Index("ix_operations_state", OperationModel.state, OperationModel.updated_at)
Index("ix_bindings_operation", IdempotencyBindingModel.operation_id)
Index("ix_payload_owner", PayloadObjectModel.controller_id, PayloadObjectModel.controller_epoch)
