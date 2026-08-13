"""Create isolated root-broker replay and recovery evidence.

Revision ID: 0001_privileged_evidence
Revises: None

No root effect handler is enabled by this migration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_privileged_evidence"
down_revision = None
branch_labels = None
depends_on = None

_DIGEST = "length(%s)=64 AND %s NOT GLOB '*[^0-9a-f]*'"


def upgrade() -> None:
    op.create_table(
        "privileged_meta",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("schema_generation", sa.Integer(), nullable=False),
        sa.Column("evidence_generation_high_water", sa.Integer(), nullable=False),
        sa.Column("broker_instance_id", sa.String(length=160), nullable=False),
        sa.Column("broker_generation", sa.Integer(), nullable=False),
        sa.Column("protocol_version", sa.String(length=32), nullable=False),
        sa.Column("build_sha256", sa.String(length=64), nullable=False),
        sa.Column("profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("readiness", sa.String(length=24), nullable=False),
        sa.Column("failure_reason", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id=1", name="ck_privileged_meta_singleton"),
        sa.CheckConstraint(
            "schema_generation=1 AND evidence_generation_high_water>=0 "
            "AND broker_generation>=1 AND updated_at>=created_at",
            name="ck_privileged_meta_generations",
        ),
        sa.CheckConstraint(
            _digest("build_sha256") + " AND " + _digest("profile_sha256"),
            name="ck_privileged_meta_digests",
        ),
        sa.CheckConstraint(
            "readiness IN "
            "('uninitialized','disabled','recovering','ready','restricted_recovery',"
            "'integrity_failed')",
            name="ck_privileged_meta_readiness",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_privileged_meta"),
    )
    zero = "0" * 64
    op.execute(
        "INSERT INTO privileged_meta "
        "(id,schema_generation,evidence_generation_high_water,broker_instance_id,"
        "broker_generation,protocol_version,build_sha256,profile_sha256,readiness,"
        "failure_reason,created_at,updated_at) VALUES "
        f"(1,1,0,'uninitialized',1,'v1','{zero}','{zero}','disabled',NULL,"
        "CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
    )

    op.create_table(
        "privileged_operation_bindings",
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("ticket_id", sa.String(length=160), nullable=False),
        sa.Column("ticket_sha256", sa.String(length=64), nullable=False),
        sa.Column("ticket_nonce_sha256", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("target_profile_id", sa.String(length=96), nullable=False),
        sa.Column("target_profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("broker_profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("current_state_binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("policy_evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acceptance_state", sa.String(length=24), nullable=False),
        sa.Column("evidence_generation", sa.Integer(), nullable=False),
        sa.Column("acceptance_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("execution_state", sa.String(length=24), nullable=False),
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("effect_knowledge", sa.String(length=24), nullable=False),
        sa.Column("result_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "action IN ('package_install','service_restart','controlled_restart')",
            name="ck_privileged_bindings_action",
        ),
        sa.CheckConstraint(
            " AND ".join(
                _digest(column)
                for column in (
                    "ticket_sha256",
                    "ticket_nonce_sha256",
                    "target_profile_sha256",
                    "broker_profile_sha256",
                    "request_fingerprint_sha256",
                    "current_state_binding_sha256",
                    "policy_evidence_sha256",
                )
            )
            + " AND (acceptance_evidence_sha256 IS NULL OR "
            + _digest("acceptance_evidence_sha256")
            + ") AND (result_evidence_sha256 IS NULL OR "
            + _digest("result_evidence_sha256")
            + ")",
            name="ck_privileged_bindings_digests",
        ),
        sa.CheckConstraint(
            "expires_at>created_at AND updated_at>=created_at AND evidence_generation>=0 "
            "AND (closed_at IS NULL OR closed_at>=created_at) "
            "AND (last_reconciled_at IS NULL OR last_reconciled_at>=created_at)",
            name="ck_privileged_bindings_time",
        ),
        sa.CheckConstraint(
            "(acceptance_state='unresolved' AND evidence_generation=0 "
            "AND acceptance_evidence_sha256 IS NULL AND accepted_at IS NULL "
            "AND sealed_at IS NULL AND execution_state='not_accepted' "
            "AND active_slot IS NULL "
            "AND effect_knowledge='none' AND result_evidence_sha256 IS NULL "
            "AND closed_at IS NULL) OR "
            "(acceptance_state='accepted' AND evidence_generation>=1 "
            "AND acceptance_evidence_sha256 IS NOT NULL AND accepted_at IS NOT NULL "
            "AND sealed_at IS NULL AND ((execution_state='accepted_pre_effect' "
            "AND active_slot=1 "
            "AND effect_knowledge='none' AND result_evidence_sha256 IS NULL "
            "AND closed_at IS NULL) OR (execution_state IN ('executing','reconciling') "
            "AND active_slot=1 "
            "AND effect_knowledge='known_effect' AND result_evidence_sha256 IS NULL "
            "AND closed_at IS NULL) OR (execution_state='terminal' "
            "AND active_slot IS NULL "
            "AND effect_knowledge IN ('known_no_subeffect','known_effect') "
            "AND result_evidence_sha256 IS NOT NULL AND closed_at IS NOT NULL) OR "
            "(execution_state IN ('uncertain','restricted_recovery') "
            "AND active_slot=1 "
            "AND effect_knowledge='uncertain' AND result_evidence_sha256 IS NOT NULL "
            "AND closed_at IS NULL))) OR "
            "(acceptance_state='sealed_no_accept' AND evidence_generation>=1 "
            "AND acceptance_evidence_sha256 IS NOT NULL AND accepted_at IS NULL "
            "AND sealed_at IS NOT NULL AND execution_state='terminal' "
            "AND active_slot IS NULL "
            "AND effect_knowledge='known_no_subeffect' "
            "AND result_evidence_sha256 IS NOT NULL AND closed_at IS NOT NULL)",
            name="ck_privileged_bindings_acceptance",
        ),
        sa.PrimaryKeyConstraint("operation_id", name="pk_privileged_operation_bindings"),
        sa.UniqueConstraint("ticket_id", name="uq_privileged_binding_ticket_id"),
        sa.UniqueConstraint("ticket_sha256", name="uq_privileged_binding_ticket_digest"),
        sa.UniqueConstraint("ticket_nonce_sha256", name="uq_privileged_binding_nonce"),
        sa.UniqueConstraint("active_slot", name="uq_privileged_binding_active_slot"),
    )

    op.create_table(
        "privileged_no_accept_tombstones",
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("ticket_id", sa.String(length=160), nullable=False),
        sa.Column("ticket_sha256", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=48), nullable=False),
        sa.Column("boot_id_sha256", sa.String(length=64), nullable=False),
        sa.Column("evidence_generation", sa.Integer(), nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("trusted_time_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "reason IN ('phase4_no_start','replacement_recovery','dispatch_cancelled')",
            name="ck_privileged_tombstones_reason",
        ),
        sa.CheckConstraint(
            _digest("ticket_sha256")
            + " AND "
            + _digest("boot_id_sha256")
            + " AND "
            + _digest("evidence_sha256"),
            name="ck_privileged_tombstones_digests",
        ),
        sa.CheckConstraint(
            "evidence_generation>=1 AND retain_until>trusted_time_at "
            "AND trusted_time_at>=created_at",
            name="ck_privileged_tombstones_time",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["privileged_operation_bindings.operation_id"],
            name="fk_privileged_tombstones_binding",
        ),
        sa.PrimaryKeyConstraint("operation_id", name="pk_privileged_no_accept_tombstones"),
        sa.UniqueConstraint("ticket_id", name="uq_privileged_tombstone_ticket"),
    )

    op.create_table(
        "privileged_subeffects",
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("subeffect_generation", sa.Integer(), nullable=False),
        sa.Column("subeffect_id", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("intent_sha256", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("effect_knowledge", sa.String(length=24), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("effect_reference", sa.String(length=160), nullable=True),
        sa.Column("boundary_receipt_sha256", sa.String(length=64), nullable=True),
        sa.Column("result_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "subeffect_generation>=1 AND updated_at>=created_at "
            "AND (started_at IS NULL OR started_at>=created_at) "
            "AND (closed_at IS NULL OR closed_at>=created_at)",
            name="ck_privileged_subeffects_time",
        ),
        sa.CheckConstraint(
            "kind IN ('package_transaction','service_stop','service_start',"
            "'selector_activate','selector_restore','runtime_verify')",
            name="ck_privileged_subeffects_kind",
        ),
        sa.CheckConstraint(
            _digest("intent_sha256")
            + " AND (boundary_receipt_sha256 IS NULL OR "
            + _digest("boundary_receipt_sha256")
            + ") AND (result_evidence_sha256 IS NULL OR "
            + _digest("result_evidence_sha256")
            + ")",
            name="ck_privileged_subeffects_digests",
        ),
        sa.CheckConstraint(
            "(state IN ('planned','intent_recorded') AND effect_knowledge='none' "
            "AND outcome='pending' "
            "AND started_at IS NULL AND closed_at IS NULL) OR "
            "(state IN ('started','reconciling') AND effect_knowledge='known_effect' "
            "AND outcome='pending' "
            "AND started_at IS NOT NULL AND closed_at IS NULL) OR "
            "(state='terminal' AND effect_knowledge IN "
            "('known_no_subeffect','known_effect') AND closed_at IS NOT NULL "
            "AND outcome IN ('succeeded','failed') "
            "AND result_evidence_sha256 IS NOT NULL) OR "
            "(state IN ('uncertain','restricted_recovery') "
            "AND effect_knowledge='uncertain' AND outcome='uncertain' "
            "AND started_at IS NOT NULL)",
            name="ck_privileged_subeffects_state",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["privileged_operation_bindings.operation_id"],
            name="fk_privileged_subeffects_binding",
        ),
        sa.PrimaryKeyConstraint(
            "operation_id",
            "subeffect_generation",
            name="pk_privileged_subeffects",
        ),
        sa.UniqueConstraint("subeffect_id", name="uq_privileged_subeffect_id"),
    )
    op.create_index(
        "uq_privileged_active_subeffect",
        "privileged_subeffects",
        ["operation_id"],
        unique=True,
        sqlite_where=sa.text(
            "state IN ('intent_recorded','started','reconciling','uncertain','restricted_recovery')"
        ),
    )

    op.create_table(
        "privileged_package_plans",
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("package_profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("repository_metadata_sha256", sa.String(length=64), nullable=False),
        sa.Column("requested_packages_sha256", sa.String(length=64), nullable=False),
        sa.Column("transaction_plan_sha256", sa.String(length=64), nullable=False),
        sa.Column("artifacts_sha256", sa.String(length=64), nullable=False),
        sa.Column("package_count", sa.Integer(), nullable=False),
        sa.Column("download_bytes", sa.Integer(), nullable=False),
        sa.Column("installed_bytes", sa.Integer(), nullable=False),
        sa.Column("parser_version", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("execute_receipt_sha256", sa.String(length=64), nullable=True),
        sa.Column("result_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            " AND ".join(
                _digest(column)
                for column in (
                    "package_profile_sha256",
                    "repository_metadata_sha256",
                    "requested_packages_sha256",
                    "transaction_plan_sha256",
                    "artifacts_sha256",
                )
            )
            + " AND (execute_receipt_sha256 IS NULL OR "
            + _digest("execute_receipt_sha256")
            + ") AND (result_evidence_sha256 IS NULL OR "
            + _digest("result_evidence_sha256")
            + ")",
            name="ck_privileged_package_plans_digests",
        ),
        sa.CheckConstraint(
            "package_count BETWEEN 1 AND 256 AND download_bytes>=0 "
            "AND installed_bytes>=0 AND updated_at>=created_at "
            "AND (verified_at IS NULL OR verified_at>=created_at) "
            "AND (closed_at IS NULL OR closed_at>=created_at)",
            name="ck_privileged_package_plans_bounds",
        ),
        sa.CheckConstraint(
            "(state='prepared' AND verified_at IS NULL AND closed_at IS NULL) OR "
            "(state='verified' AND verified_at IS NOT NULL AND closed_at IS NULL) OR "
            "(state='executing' AND verified_at IS NOT NULL "
            "AND closed_at IS NULL) OR "
            "(state='terminal' AND verified_at IS NOT NULL AND closed_at IS NOT NULL "
            "AND result_evidence_sha256 IS NOT NULL) OR "
            "(state='uncertain' AND verified_at IS NOT NULL AND closed_at IS NULL)",
            name="ck_privileged_package_plans_state",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["privileged_operation_bindings.operation_id"],
            name="fk_privileged_package_plans_binding",
        ),
        sa.PrimaryKeyConstraint("operation_id", name="pk_privileged_package_plans"),
        sa.UniqueConstraint(
            "transaction_plan_sha256",
            name="uq_privileged_package_transaction_plan",
        ),
    )

    op.create_table(
        "privileged_runtime_slots",
        sa.Column("slot_id", sa.String(length=160), nullable=False),
        sa.Column("slot_generation", sa.Integer(), nullable=False),
        sa.Column("slot_path", sa.String(length=512), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("environment_sha256", sa.String(length=64), nullable=False),
        sa.Column("config_sha256", sa.String(length=64), nullable=False),
        sa.Column("policy_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("service_definition_sha256", sa.String(length=64), nullable=False),
        sa.Column("deployed_peer_set_sha256", sa.String(length=64), nullable=False),
        sa.Column("migration_heads_sha256", sa.String(length=64), nullable=False),
        sa.Column("layout_sha256", sa.String(length=64), nullable=False),
        sa.Column("candidate_verification_sha256", sa.String(length=64), nullable=False),
        sa.Column("complete_manifest_sha256", sa.String(length=64), nullable=True),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("inode_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "slot_generation>=1 AND byte_count BETWEEN 0 AND 100000000000 "
            "AND inode_count BETWEEN 0 AND 10000000 AND updated_at>=created_at "
            "AND (completed_at IS NULL OR completed_at>=created_at)",
            name="ck_privileged_runtime_slots_bounds",
        ),
        sa.CheckConstraint(
            "length(slot_id) BETWEEN 1 AND 160 "
            "AND slot_id GLOB '[a-z0-9]*' "
            "AND slot_id NOT GLOB '*[^a-z0-9._-]*' "
            "AND instr(slot_id,'..')=0 "
            "AND slot_path='/srv/binnacle-runtime/slots/' || slot_id",
            name="ck_privileged_runtime_slots_path",
        ),
        sa.CheckConstraint(
            " AND ".join(
                _digest(column)
                for column in (
                    "source_sha256",
                    "environment_sha256",
                    "config_sha256",
                    "policy_sha256",
                    "manifest_sha256",
                    "service_definition_sha256",
                    "deployed_peer_set_sha256",
                    "migration_heads_sha256",
                    "layout_sha256",
                    "candidate_verification_sha256",
                )
            )
            + " AND (complete_manifest_sha256 IS NULL OR "
            + _digest("complete_manifest_sha256")
            + ")",
            name="ck_privileged_runtime_slots_digests",
        ),
        sa.CheckConstraint(
            "role IN ('candidate','lkg','prior') AND "
            "((state='staging' AND completed_at IS NULL "
            "AND complete_manifest_sha256 IS NULL) OR "
            "(state IN ('complete','active','lkg','prior') "
            "AND completed_at IS NOT NULL AND complete_manifest_sha256 IS NOT NULL "
            "AND byte_count>0 AND inode_count>0) OR "
            "(state='restricted' AND "
            "((completed_at IS NULL AND complete_manifest_sha256 IS NULL) OR "
            "(completed_at IS NOT NULL AND complete_manifest_sha256 IS NOT NULL "
            "AND byte_count>0 AND inode_count>0))))",
            name="ck_privileged_runtime_slots_state",
        ),
        sa.PrimaryKeyConstraint("slot_id", name="pk_privileged_runtime_slots"),
        sa.UniqueConstraint("slot_generation", name="uq_privileged_runtime_slot_generation"),
        sa.UniqueConstraint("slot_path", name="uq_privileged_runtime_slot_path"),
    )
    op.create_index(
        "uq_privileged_active_runtime_slot",
        "privileged_runtime_slots",
        ["state"],
        unique=True,
        sqlite_where=sa.text("state='active'"),
    )
    op.create_index(
        "uq_privileged_lkg_runtime_slot",
        "privileged_runtime_slots",
        ["state"],
        unique=True,
        sqlite_where=sa.text("state='lkg'"),
    )

    op.create_table(
        "privileged_restart_checkpoints",
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("service_profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=160), nullable=False),
        sa.Column("workspace_fence_version", sa.Integer(), nullable=False),
        sa.Column("evidence_generation", sa.Integer(), nullable=False),
        sa.Column("candidate_slot_id", sa.String(length=160), nullable=False),
        sa.Column("lkg_slot_id", sa.String(length=160), nullable=False),
        sa.Column("selected_slot_id", sa.String(length=160), nullable=True),
        sa.Column("current_runtime_identity_sha256", sa.String(length=64), nullable=False),
        sa.Column("current_service_observation_sha256", sa.String(length=64), nullable=False),
        sa.Column("outstanding_state_sha256", sa.String(length=64), nullable=False),
        sa.Column("preflight_state_binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("preflight_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_verification_sha256", sa.String(length=64), nullable=False),
        sa.Column("peer_set_sha256", sa.String(length=64), nullable=False),
        sa.Column("schema_heads_sha256", sa.String(length=64), nullable=False),
        sa.Column("restart_deadline_seconds", sa.Integer(), nullable=False),
        sa.Column("checkpoint_sha256", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("result_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("service_stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "workspace_fence_version>=1 AND evidence_generation>=1 "
            "AND restart_deadline_seconds BETWEEN 1 AND 900 AND updated_at>=created_at "
            "AND preflight_observed_at<=created_at "
            "AND (service_stopped_at IS NULL OR service_stopped_at>=created_at) "
            "AND (closed_at IS NULL OR closed_at>=created_at)",
            name="ck_privileged_restart_checkpoints_time",
        ),
        sa.CheckConstraint(
            " AND ".join(
                _digest(column)
                for column in (
                    "service_profile_sha256",
                    "current_runtime_identity_sha256",
                    "current_service_observation_sha256",
                    "outstanding_state_sha256",
                    "preflight_state_binding_sha256",
                    "candidate_verification_sha256",
                    "peer_set_sha256",
                    "schema_heads_sha256",
                    "checkpoint_sha256",
                )
            )
            + " AND (result_evidence_sha256 IS NULL OR "
            + _digest("result_evidence_sha256")
            + ")",
            name="ck_privileged_restart_checkpoints_digests",
        ),
        sa.CheckConstraint(
            "(state IN ('prepared','checkpointed') AND outcome='pending' "
            "AND service_stopped_at IS NULL "
            "AND selected_slot_id IS NULL AND closed_at IS NULL) OR "
            "(state='service_stopped' AND outcome='pending' AND service_stopped_at IS NOT NULL "
            "AND selected_slot_id IS NULL AND closed_at IS NULL) OR "
            "(state IN ('candidate_selected','candidate_started','verifying') "
            "AND outcome='pending' "
            "AND service_stopped_at IS NOT NULL AND selected_slot_id=candidate_slot_id "
            "AND closed_at IS NULL) OR "
            "(state='rollback_required' AND outcome='pending' "
            "AND service_stopped_at IS NOT NULL "
            "AND (selected_slot_id IS NULL OR selected_slot_id=candidate_slot_id) "
            "AND closed_at IS NULL) OR "
            "(state='rollback_service_stopped' AND outcome='pending' "
            "AND service_stopped_at IS NOT NULL "
            "AND (selected_slot_id IS NULL OR selected_slot_id=candidate_slot_id) "
            "AND closed_at IS NULL) OR "
            "(state IN ('rollback_selected','rollback_started') "
            "AND outcome='pending' "
            "AND service_stopped_at IS NOT NULL AND selected_slot_id=lkg_slot_id "
            "AND closed_at IS NULL) OR "
            "(state='restricted_recovery' "
            "AND outcome='restricted_recovery' AND result_evidence_sha256 IS NOT NULL "
            "AND closed_at IS NULL) OR "
            "(state='terminal' AND closed_at IS NOT NULL "
            "AND outcome IN ('candidate_ready','rollback_ready','no_subeffect','failed') "
            "AND result_evidence_sha256 IS NOT NULL)",
            name="ck_privileged_restart_checkpoints_state",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["privileged_operation_bindings.operation_id"],
            name="fk_privileged_restart_binding",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_slot_id"],
            ["privileged_runtime_slots.slot_id"],
            name="fk_privileged_restart_candidate_slot",
        ),
        sa.ForeignKeyConstraint(
            ["lkg_slot_id"],
            ["privileged_runtime_slots.slot_id"],
            name="fk_privileged_restart_lkg_slot",
        ),
        sa.ForeignKeyConstraint(
            ["selected_slot_id"],
            ["privileged_runtime_slots.slot_id"],
            name="fk_privileged_restart_selected_slot",
        ),
        sa.PrimaryKeyConstraint("operation_id", name="pk_privileged_restart_checkpoints"),
    )

    op.create_table(
        "privileged_selector_generations",
        sa.Column("selector_generation", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.String(length=160), nullable=True),
        sa.Column("initial_bootstrap", sa.Boolean(), nullable=False),
        sa.Column("old_slot_id", sa.String(length=160), nullable=True),
        sa.Column("new_slot_id", sa.String(length=160), nullable=False),
        sa.Column("intent_sha256", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("publication_receipt_sha256", sa.String(length=64), nullable=True),
        sa.Column("verification_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "selector_generation>=1 AND (initial_bootstrap=1)=(operation_id IS NULL) "
            "AND (initial_bootstrap=0 OR old_slot_id IS NULL) "
            "AND updated_at>=created_at "
            "AND (published_at IS NULL OR published_at>=created_at) "
            "AND (verified_at IS NULL OR verified_at>=created_at)",
            name="ck_privileged_selector_generations_time",
        ),
        sa.CheckConstraint(
            _digest("intent_sha256")
            + " AND (publication_receipt_sha256 IS NULL OR "
            + _digest("publication_receipt_sha256")
            + ") AND (verification_evidence_sha256 IS NULL OR "
            + _digest("verification_evidence_sha256")
            + ")",
            name="ck_privileged_selector_generations_digests",
        ),
        sa.CheckConstraint(
            "(state='intent_recorded' AND published_at IS NULL AND verified_at IS NULL) OR "
            "(state='published' AND published_at IS NOT NULL "
            "AND publication_receipt_sha256 IS NOT NULL AND verified_at IS NULL) OR "
            "(state='uncertain' AND published_at IS NOT NULL AND verified_at IS NULL) OR "
            "(state='not_published' AND published_at IS NULL "
            "AND publication_receipt_sha256 IS NULL AND verified_at IS NOT NULL "
            "AND verification_evidence_sha256 IS NOT NULL) OR "
            "(state IN ('verified','restored') AND published_at IS NOT NULL "
            "AND verified_at IS NOT NULL AND publication_receipt_sha256 IS NOT NULL "
            "AND verification_evidence_sha256 IS NOT NULL)",
            name="ck_privileged_selector_generations_state",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["privileged_operation_bindings.operation_id"],
            name="fk_privileged_selector_binding",
        ),
        sa.ForeignKeyConstraint(
            ["old_slot_id"],
            ["privileged_runtime_slots.slot_id"],
            name="fk_privileged_selector_old_slot",
        ),
        sa.ForeignKeyConstraint(
            ["new_slot_id"],
            ["privileged_runtime_slots.slot_id"],
            name="fk_privileged_selector_new_slot",
        ),
        sa.PrimaryKeyConstraint(
            "selector_generation",
            name="pk_privileged_selector_generations",
        ),
    )
    op.create_index(
        "uq_privileged_initial_selector_generation",
        "privileged_selector_generations",
        ["initial_bootstrap"],
        unique=True,
        sqlite_where=sa.text("initial_bootstrap=1"),
    )

    op.create_table(
        "privileged_evidence_events",
        sa.Column("evidence_generation", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=160), nullable=False),
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_sha256", sa.String(length=64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "evidence_generation>=1 AND " + _digest("event_sha256"),
            name="ck_privileged_events_shape",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["privileged_operation_bindings.operation_id"],
            name="fk_privileged_events_binding",
        ),
        sa.PrimaryKeyConstraint(
            "evidence_generation",
            name="pk_privileged_evidence_events",
        ),
        sa.UniqueConstraint("event_id", name="uq_privileged_event_id"),
    )

    for table in (
        "privileged_operation_bindings",
        "privileged_no_accept_tombstones",
        "privileged_subeffects",
        "privileged_package_plans",
        "privileged_runtime_slots",
        "privileged_restart_checkpoints",
        "privileged_selector_generations",
        "privileged_evidence_events",
    ):
        op.execute(
            f"""
            CREATE TRIGGER {table}_no_delete
            BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT, 'privileged evidence is retained'); END
            """
        )

    op.execute(
        """
        CREATE TRIGGER privileged_meta_guarded_update
        BEFORE UPDATE ON privileged_meta
        BEGIN
          SELECT CASE WHEN NEW.id!=OLD.id OR
            NEW.schema_generation!=OLD.schema_generation OR
            NEW.created_at!=OLD.created_at OR
            NEW.evidence_generation_high_water<OLD.evidence_generation_high_water OR
            NEW.broker_generation<OLD.broker_generation OR NEW.updated_at<OLD.updated_at OR
            ((NEW.broker_instance_id!=OLD.broker_instance_id OR
              NEW.protocol_version!=OLD.protocol_version OR
              NEW.build_sha256!=OLD.build_sha256 OR NEW.profile_sha256!=OLD.profile_sha256)
             AND NEW.broker_generation=OLD.broker_generation)
          THEN RAISE(ABORT, 'privileged metadata regressed') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER privileged_meta_no_delete
        BEFORE DELETE ON privileged_meta
        BEGIN SELECT RAISE(ABORT, 'privileged metadata is retained'); END
        """
    )
    op.execute(
        """
        CREATE TRIGGER privileged_bindings_guarded_update
        BEFORE UPDATE ON privileged_operation_bindings
        BEGIN
          SELECT CASE WHEN NEW.operation_id!=OLD.operation_id OR
            NEW.ticket_id!=OLD.ticket_id OR NEW.ticket_sha256!=OLD.ticket_sha256 OR
            NEW.ticket_nonce_sha256!=OLD.ticket_nonce_sha256 OR NEW.action!=OLD.action OR
            NEW.target_profile_id!=OLD.target_profile_id OR
            NEW.target_profile_sha256!=OLD.target_profile_sha256 OR
            NEW.broker_profile_sha256!=OLD.broker_profile_sha256 OR
            NEW.request_fingerprint_sha256!=OLD.request_fingerprint_sha256 OR
            NEW.current_state_binding_sha256!=OLD.current_state_binding_sha256 OR
            NEW.policy_evidence_sha256!=OLD.policy_evidence_sha256 OR
            NEW.expires_at!=OLD.expires_at OR NEW.created_at!=OLD.created_at
          THEN RAISE(ABORT, 'privileged ticket binding changed') END;
          SELECT CASE WHEN NEW.evidence_generation<OLD.evidence_generation OR
            NEW.updated_at<OLD.updated_at OR
            (OLD.acceptance_state!='unresolved' AND
             NEW.acceptance_state!=OLD.acceptance_state) OR
            (OLD.acceptance_evidence_sha256 IS NOT NULL AND
             NEW.acceptance_evidence_sha256 IS NOT OLD.acceptance_evidence_sha256) OR
            (OLD.accepted_at IS NOT NULL AND NEW.accepted_at IS NOT OLD.accepted_at) OR
            (OLD.sealed_at IS NOT NULL AND NEW.sealed_at IS NOT OLD.sealed_at)
            OR (OLD.result_evidence_sha256 IS NOT NULL AND
                NEW.result_evidence_sha256 IS NOT OLD.result_evidence_sha256)
            OR (OLD.closed_at IS NOT NULL AND NEW.closed_at IS NOT OLD.closed_at)
            OR (OLD.last_reconciled_at IS NOT NULL AND
                NEW.last_reconciled_at<OLD.last_reconciled_at)
            OR NOT (NEW.active_slot IS OLD.active_slot OR
              (OLD.active_slot IS NULL AND NEW.active_slot=1 AND
               OLD.acceptance_state='unresolved' AND NEW.acceptance_state='accepted') OR
              (OLD.active_slot=1 AND NEW.active_slot IS NULL AND
               NEW.execution_state='terminal'))
            OR NOT (NEW.execution_state=OLD.execution_state OR
              (OLD.execution_state='not_accepted' AND NEW.execution_state IN
               ('accepted_pre_effect','terminal')) OR
              (OLD.execution_state='accepted_pre_effect' AND NEW.execution_state IN
               ('executing','terminal','uncertain','restricted_recovery')) OR
              (OLD.execution_state='executing' AND NEW.execution_state IN
               ('reconciling','terminal','uncertain','restricted_recovery')) OR
              (OLD.execution_state='reconciling' AND NEW.execution_state IN
               ('terminal','uncertain','restricted_recovery')) OR
              (OLD.execution_state='uncertain' AND NEW.execution_state IN
               ('reconciling','terminal','restricted_recovery')) OR
              (OLD.execution_state='restricted_recovery' AND NEW.execution_state IN
               ('reconciling','terminal')))
            OR NOT (NEW.effect_knowledge=OLD.effect_knowledge OR
              (OLD.effect_knowledge='none' AND NEW.effect_knowledge IN
               ('known_no_subeffect','known_effect','uncertain')) OR
              (OLD.effect_knowledge='known_effect' AND NEW.effect_knowledge='uncertain') OR
              (OLD.effect_knowledge='uncertain' AND NEW.effect_knowledge IN
               ('known_no_subeffect','known_effect')))
          THEN RAISE(ABORT, 'privileged acceptance evidence regressed') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER privileged_bindings_reject_accept_after_tombstone
        BEFORE UPDATE OF acceptance_state ON privileged_operation_bindings
        WHEN NEW.acceptance_state='accepted'
        BEGIN
          SELECT CASE WHEN EXISTS (
            SELECT 1 FROM privileged_no_accept_tombstones tombstone
            WHERE tombstone.operation_id=NEW.operation_id
          ) THEN RAISE(ABORT, 'privileged no-accept seal already won') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER privileged_tombstones_validate_binding
        BEFORE INSERT ON privileged_no_accept_tombstones
        BEGIN
          SELECT CASE WHEN NOT EXISTS (
            SELECT 1 FROM privileged_operation_bindings binding
            WHERE binding.operation_id=NEW.operation_id
              AND binding.ticket_id=NEW.ticket_id
              AND binding.ticket_sha256=NEW.ticket_sha256
              AND binding.acceptance_state!='accepted'
          ) THEN RAISE(ABORT, 'privileged tombstone conflicts with ticket binding') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER privileged_tombstones_no_update
        BEFORE UPDATE ON privileged_no_accept_tombstones
        BEGIN SELECT RAISE(ABORT, 'privileged tombstone is immutable'); END
        """
    )
    op.execute(
        """
        CREATE TRIGGER privileged_subeffects_guarded_update
        BEFORE UPDATE ON privileged_subeffects
        BEGIN
          SELECT CASE WHEN NEW.operation_id!=OLD.operation_id OR
            NEW.subeffect_generation!=OLD.subeffect_generation OR
            NEW.subeffect_id!=OLD.subeffect_id OR NEW.kind!=OLD.kind OR
            NEW.intent_sha256!=OLD.intent_sha256 OR NEW.created_at!=OLD.created_at
          THEN RAISE(ABORT, 'privileged subeffect identity changed') END;
          SELECT CASE WHEN NEW.updated_at<OLD.updated_at OR
            (OLD.effect_reference IS NOT NULL AND
             NEW.effect_reference IS NOT OLD.effect_reference) OR
            (OLD.boundary_receipt_sha256 IS NOT NULL AND
             NEW.boundary_receipt_sha256 IS NOT OLD.boundary_receipt_sha256) OR
            (OLD.result_evidence_sha256 IS NOT NULL AND
             NEW.result_evidence_sha256 IS NOT OLD.result_evidence_sha256) OR
            (OLD.outcome!='pending' AND NEW.outcome!=OLD.outcome) OR
            (OLD.started_at IS NOT NULL AND NEW.started_at IS NOT OLD.started_at) OR
            (OLD.closed_at IS NOT NULL AND NEW.closed_at IS NOT OLD.closed_at) OR
            NOT (
              NEW.state=OLD.state OR
              (OLD.state='planned' AND NEW.state IN
               ('intent_recorded','terminal','uncertain')) OR
              (OLD.state='intent_recorded' AND NEW.state IN
               ('started','terminal','uncertain')) OR
              (OLD.state='started' AND NEW.state IN
               ('reconciling','terminal','uncertain','restricted_recovery')) OR
              (OLD.state='reconciling' AND NEW.state IN
               ('terminal','uncertain','restricted_recovery')) OR
              (OLD.state='uncertain' AND NEW.state IN
               ('terminal','restricted_recovery')) OR
              (OLD.state='restricted_recovery' AND NEW.state='terminal')
            ) OR NOT (
              NEW.effect_knowledge=OLD.effect_knowledge OR
              (OLD.effect_knowledge='none' AND NEW.effect_knowledge IN
               ('known_no_subeffect','known_effect','uncertain')) OR
              (OLD.effect_knowledge='uncertain' AND NEW.effect_knowledge IN
               ('known_no_subeffect','known_effect'))
            ) OR (OLD.state='terminal' AND NEW.state!='terminal')
          THEN RAISE(ABORT, 'privileged subeffect evidence regressed') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER privileged_events_no_update
        BEFORE UPDATE ON privileged_evidence_events
        BEGIN SELECT RAISE(ABORT, 'privileged event evidence is immutable'); END
        """
    )
    op.execute(
        """
        CREATE TRIGGER privileged_package_plans_guarded_update
        BEFORE UPDATE ON privileged_package_plans
        BEGIN
          SELECT CASE WHEN NEW.operation_id!=OLD.operation_id OR
            NEW.package_profile_sha256!=OLD.package_profile_sha256 OR
            NEW.repository_metadata_sha256!=OLD.repository_metadata_sha256 OR
            NEW.requested_packages_sha256!=OLD.requested_packages_sha256 OR
            NEW.transaction_plan_sha256!=OLD.transaction_plan_sha256 OR
            NEW.artifacts_sha256!=OLD.artifacts_sha256 OR
            NEW.package_count!=OLD.package_count OR NEW.download_bytes!=OLD.download_bytes OR
            NEW.installed_bytes!=OLD.installed_bytes OR
            NEW.parser_version!=OLD.parser_version OR NEW.created_at!=OLD.created_at
          THEN RAISE(ABORT, 'privileged package plan identity changed') END;
          SELECT CASE WHEN NEW.updated_at<OLD.updated_at OR
            (OLD.execute_receipt_sha256 IS NOT NULL AND
             NEW.execute_receipt_sha256 IS NOT OLD.execute_receipt_sha256) OR
            (OLD.result_evidence_sha256 IS NOT NULL AND
             NEW.result_evidence_sha256 IS NOT OLD.result_evidence_sha256) OR
            (OLD.verified_at IS NOT NULL AND NEW.verified_at IS NOT OLD.verified_at) OR
            (OLD.closed_at IS NOT NULL AND NEW.closed_at IS NOT OLD.closed_at) OR
            NOT (NEW.state=OLD.state OR
              (OLD.state='prepared' AND NEW.state IN ('verified','uncertain')) OR
              (OLD.state='verified' AND NEW.state IN ('executing','terminal','uncertain')) OR
              (OLD.state='executing' AND NEW.state IN ('terminal','uncertain')) OR
              (OLD.state='uncertain' AND NEW.state='terminal')) OR
            (OLD.state='terminal' AND NEW.state!='terminal')
          THEN RAISE(ABORT, 'privileged package plan evidence regressed') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER privileged_runtime_slots_guarded_update
        BEFORE UPDATE ON privileged_runtime_slots
        BEGIN
          SELECT CASE WHEN NEW.slot_id!=OLD.slot_id OR
            NEW.slot_generation!=OLD.slot_generation OR NEW.slot_path!=OLD.slot_path OR
            NEW.role!=OLD.role OR NEW.source_sha256!=OLD.source_sha256 OR
            NEW.environment_sha256!=OLD.environment_sha256 OR
            NEW.config_sha256!=OLD.config_sha256 OR NEW.policy_sha256!=OLD.policy_sha256 OR
            NEW.manifest_sha256!=OLD.manifest_sha256 OR
            NEW.service_definition_sha256!=OLD.service_definition_sha256 OR
            NEW.deployed_peer_set_sha256!=OLD.deployed_peer_set_sha256 OR
            NEW.migration_heads_sha256!=OLD.migration_heads_sha256 OR
            NEW.layout_sha256!=OLD.layout_sha256 OR
            NEW.candidate_verification_sha256!=OLD.candidate_verification_sha256 OR
            NEW.byte_count!=OLD.byte_count OR
            NEW.inode_count!=OLD.inode_count OR NEW.created_at!=OLD.created_at
          THEN RAISE(ABORT, 'privileged runtime slot identity changed') END;
          SELECT CASE WHEN NEW.updated_at<OLD.updated_at OR
            (OLD.complete_manifest_sha256 IS NOT NULL AND
             NEW.complete_manifest_sha256 IS NOT OLD.complete_manifest_sha256) OR
            (OLD.completed_at IS NOT NULL AND NEW.completed_at IS NOT OLD.completed_at) OR
            NOT (NEW.state=OLD.state OR
              (OLD.state='staging' AND NEW.state IN ('complete','restricted')) OR
              (OLD.state='complete' AND NEW.state IN ('active','lkg','prior','restricted')) OR
              (OLD.state='active' AND NEW.state IN ('lkg','prior','restricted')) OR
              (OLD.state='lkg' AND NEW.state IN ('prior','restricted')) OR
              (OLD.state='prior' AND NEW.state='restricted'))
          THEN RAISE(ABORT, 'privileged runtime slot evidence regressed') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER privileged_restart_checkpoints_guarded_update
        BEFORE UPDATE ON privileged_restart_checkpoints
        BEGIN
          SELECT CASE WHEN NEW.operation_id!=OLD.operation_id OR
            NEW.service_profile_sha256!=OLD.service_profile_sha256 OR
            NEW.workspace_id!=OLD.workspace_id OR
            NEW.workspace_fence_version!=OLD.workspace_fence_version OR
            NEW.evidence_generation<OLD.evidence_generation OR
            NEW.candidate_slot_id!=OLD.candidate_slot_id OR NEW.lkg_slot_id!=OLD.lkg_slot_id OR
            NEW.current_runtime_identity_sha256!=OLD.current_runtime_identity_sha256 OR
            NEW.current_service_observation_sha256!=OLD.current_service_observation_sha256 OR
            NEW.outstanding_state_sha256!=OLD.outstanding_state_sha256 OR
            NEW.preflight_state_binding_sha256!=OLD.preflight_state_binding_sha256 OR
            NEW.preflight_observed_at!=OLD.preflight_observed_at OR
            NEW.candidate_verification_sha256!=OLD.candidate_verification_sha256 OR
            NEW.peer_set_sha256!=OLD.peer_set_sha256 OR
            NEW.schema_heads_sha256!=OLD.schema_heads_sha256 OR
            NEW.restart_deadline_seconds!=OLD.restart_deadline_seconds OR
            NEW.checkpoint_sha256!=OLD.checkpoint_sha256 OR NEW.created_at!=OLD.created_at
          THEN RAISE(ABORT, 'privileged restart checkpoint identity changed') END;
          SELECT CASE WHEN NEW.updated_at<OLD.updated_at OR
            NOT (NEW.selected_slot_id IS OLD.selected_slot_id OR
              (OLD.selected_slot_id IS NULL AND
               NEW.selected_slot_id IS NOT NULL AND
               (NEW.selected_slot_id IS NEW.candidate_slot_id OR
                NEW.selected_slot_id IS NEW.lkg_slot_id)) OR
              (OLD.selected_slot_id IS OLD.candidate_slot_id AND
               NEW.selected_slot_id IS NEW.lkg_slot_id)) OR
            (OLD.result_evidence_sha256 IS NOT NULL AND
             NEW.result_evidence_sha256 IS NOT OLD.result_evidence_sha256) OR
            (OLD.outcome!='pending' AND NEW.outcome!=OLD.outcome) OR
            (OLD.service_stopped_at IS NOT NULL AND
             NEW.service_stopped_at IS NOT OLD.service_stopped_at) OR
            (OLD.closed_at IS NOT NULL AND NEW.closed_at IS NOT OLD.closed_at) OR
            NOT (NEW.state=OLD.state OR
              (OLD.state='prepared' AND
               NEW.state IN ('checkpointed','terminal','restricted_recovery')) OR
              (OLD.state='checkpointed' AND NEW.state IN
               ('service_stopped','terminal','restricted_recovery')) OR
              (OLD.state='service_stopped' AND NEW.state IN
               ('candidate_selected','rollback_required','restricted_recovery')) OR
              (OLD.state='candidate_selected' AND NEW.state IN
               ('candidate_started','rollback_required','restricted_recovery')) OR
              (OLD.state='candidate_started' AND NEW.state IN
               ('verifying','rollback_required','restricted_recovery')) OR
              (OLD.state='verifying' AND NEW.state IN
               ('terminal','rollback_required','restricted_recovery')) OR
              (OLD.state='rollback_required' AND NEW.state IN
               ('rollback_service_stopped','restricted_recovery')) OR
              (OLD.state='rollback_service_stopped' AND NEW.state IN
               ('rollback_selected','restricted_recovery')) OR
              (OLD.state='rollback_selected' AND NEW.state IN
               ('rollback_started','restricted_recovery')) OR
              (OLD.state='rollback_started' AND NEW.state IN
               ('terminal','restricted_recovery')) OR
              (OLD.state='restricted_recovery' AND NEW.state='terminal')) OR
            (OLD.state='terminal' AND NEW.state!='terminal')
          THEN RAISE(ABORT, 'privileged restart checkpoint evidence regressed') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER privileged_selector_generations_guarded_update
        BEFORE UPDATE ON privileged_selector_generations
        BEGIN
          SELECT CASE WHEN NEW.selector_generation!=OLD.selector_generation OR
            NEW.operation_id IS NOT OLD.operation_id OR
            NEW.initial_bootstrap!=OLD.initial_bootstrap OR
            NEW.old_slot_id IS NOT OLD.old_slot_id OR NEW.new_slot_id!=OLD.new_slot_id OR
            NEW.intent_sha256!=OLD.intent_sha256 OR NEW.created_at!=OLD.created_at
          THEN RAISE(ABORT, 'privileged selector identity changed') END;
          SELECT CASE WHEN NEW.updated_at<OLD.updated_at OR
            (OLD.publication_receipt_sha256 IS NOT NULL AND
             NEW.publication_receipt_sha256 IS NOT OLD.publication_receipt_sha256) OR
            (OLD.verification_evidence_sha256 IS NOT NULL AND
             NEW.verification_evidence_sha256 IS NOT OLD.verification_evidence_sha256) OR
            (OLD.published_at IS NOT NULL AND NEW.published_at IS NOT OLD.published_at) OR
            (OLD.verified_at IS NOT NULL AND NEW.verified_at IS NOT OLD.verified_at) OR
            NOT (NEW.state=OLD.state OR
              (OLD.state='intent_recorded' AND
               NEW.state IN ('published','uncertain','not_published')) OR
              (OLD.state='published' AND NEW.state IN ('verified','restored')) OR
              (OLD.state='uncertain' AND
               NEW.state IN ('published','verified','restored')))
          THEN RAISE(ABORT, 'privileged selector evidence regressed') END;
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER privileged_selector_generations_guarded_update")
    op.execute("DROP TRIGGER privileged_restart_checkpoints_guarded_update")
    op.execute("DROP TRIGGER privileged_runtime_slots_guarded_update")
    op.execute("DROP TRIGGER privileged_package_plans_guarded_update")
    op.execute("DROP TRIGGER privileged_events_no_update")
    op.execute("DROP TRIGGER privileged_subeffects_guarded_update")
    op.execute("DROP TRIGGER privileged_tombstones_no_update")
    op.execute("DROP TRIGGER privileged_tombstones_validate_binding")
    op.execute("DROP TRIGGER privileged_bindings_reject_accept_after_tombstone")
    op.execute("DROP TRIGGER privileged_bindings_guarded_update")
    op.execute("DROP TRIGGER privileged_meta_no_delete")
    op.execute("DROP TRIGGER privileged_meta_guarded_update")
    for table in reversed(
        (
            "privileged_operation_bindings",
            "privileged_no_accept_tombstones",
            "privileged_subeffects",
            "privileged_package_plans",
            "privileged_runtime_slots",
            "privileged_restart_checkpoints",
            "privileged_selector_generations",
            "privileged_evidence_events",
        )
    ):
        op.execute(f"DROP TRIGGER {table}_no_delete")
    op.drop_table("privileged_evidence_events")
    op.drop_index(
        "uq_privileged_initial_selector_generation",
        table_name="privileged_selector_generations",
    )
    op.drop_table("privileged_selector_generations")
    op.drop_table("privileged_restart_checkpoints")
    op.drop_index("uq_privileged_lkg_runtime_slot", table_name="privileged_runtime_slots")
    op.drop_index("uq_privileged_active_runtime_slot", table_name="privileged_runtime_slots")
    op.drop_table("privileged_runtime_slots")
    op.drop_table("privileged_package_plans")
    op.drop_index("uq_privileged_active_subeffect", table_name="privileged_subeffects")
    op.drop_table("privileged_subeffects")
    op.drop_table("privileged_no_accept_tombstones")
    op.drop_table("privileged_operation_bindings")
    op.drop_table("privileged_meta")


def _digest(column: str) -> str:
    return _DIGEST % (column, column)
