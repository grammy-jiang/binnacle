"""Add authoritative Phase 9 preparation, ticket, and restart-fence evidence.

Revision ID: 0006_privileged_operations
Revises: 0005_git_operations

This migration adds no privileged handler or MCP surface.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_privileged_operations"
down_revision = "0005_git_operations"
branch_labels = None
depends_on = None

_ACTIONS = "('package_install','service_restart','controlled_restart')"
_MAXIMUM_EFFECTS = "('package_change','service_restart','controlled_restart')"


def upgrade() -> None:
    op.create_table(
        "privileged_preparations",
        sa.Column("prepare_operation_id", sa.String(length=160), nullable=False),
        sa.Column("session_id", sa.String(length=160), nullable=True),
        sa.Column("workspace_id", sa.String(length=160), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("target_profile_id", sa.String(length=96), nullable=False),
        sa.Column("target_profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("maximum_effect", sa.String(length=32), nullable=False),
        sa.Column("normalized_request_sha256", sa.String(length=64), nullable=False),
        sa.Column("current_state_binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("prepared_evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("execution_nonce_sha256", sa.String(length=64), nullable=False),
        sa.Column("package_transaction_plan_sha256", sa.String(length=64), nullable=True),
        sa.Column("service_profile_sha256", sa.String(length=64), nullable=True),
        sa.Column("candidate_verification_reference", sa.String(length=160), nullable=True),
        sa.Column("candidate_verification_sha256", sa.String(length=64), nullable=True),
        sa.Column("candidate_slot_id", sa.String(length=160), nullable=True),
        sa.Column("lkg_slot_id", sa.String(length=160), nullable=True),
        sa.Column("schema_heads_sha256", sa.String(length=64), nullable=True),
        sa.Column("runtime_layout_sha256", sa.String(length=64), nullable=True),
        sa.Column("deployed_peer_set_sha256", sa.String(length=64), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("consumed_by_operation_id", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"action IN {_ACTIONS}", name="ck_privileged_preparations_action"),
        sa.CheckConstraint(
            f"maximum_effect IN {_MAXIMUM_EFFECTS} AND "
            "((action='package_install' AND maximum_effect='package_change') OR "
            "(action='service_restart' AND maximum_effect='service_restart') OR "
            "(action='controlled_restart' AND maximum_effect='controlled_restart'))",
            name="ck_privileged_preparations_effect",
        ),
        sa.CheckConstraint(
            _digests(
                "target_profile_sha256",
                "normalized_request_sha256",
                "current_state_binding_sha256",
                "prepared_evidence_sha256",
                "execution_nonce_sha256",
            )
            + " AND "
            + _optional_digests(
                "package_transaction_plan_sha256",
                "service_profile_sha256",
                "candidate_verification_sha256",
                "schema_heads_sha256",
                "runtime_layout_sha256",
                "deployed_peer_set_sha256",
            ),
            name="ck_privileged_preparations_digests",
        ),
        sa.CheckConstraint(
            "expires_at>created_at AND updated_at>=created_at "
            "AND (consumed_at IS NULL OR consumed_at>=created_at) "
            "AND ((state='available' AND consumed_by_operation_id IS NULL "
            "AND consumed_at IS NULL) OR "
            "(state='consumed' AND consumed_by_operation_id IS NOT NULL "
            "AND consumed_at IS NOT NULL) OR "
            "(state='expired' AND consumed_by_operation_id IS NULL AND consumed_at IS NULL))",
            name="ck_privileged_preparations_state",
        ),
        sa.CheckConstraint(
            "(action='package_install' AND session_id IS NULL AND workspace_id IS NULL "
            "AND package_transaction_plan_sha256 IS NOT NULL "
            "AND service_profile_sha256 IS NULL "
            "AND candidate_verification_reference IS NULL "
            "AND candidate_verification_sha256 IS NULL AND candidate_slot_id IS NULL "
            "AND lkg_slot_id IS NULL AND schema_heads_sha256 IS NULL "
            "AND runtime_layout_sha256 IS NULL AND deployed_peer_set_sha256 IS NULL) OR "
            "(action='service_restart' AND session_id IS NOT NULL AND workspace_id IS NOT NULL "
            "AND package_transaction_plan_sha256 IS NULL "
            "AND service_profile_sha256 IS NOT NULL "
            "AND candidate_verification_reference IS NOT NULL "
            "AND candidate_verification_sha256 IS NOT NULL AND candidate_slot_id IS NULL "
            "AND lkg_slot_id IS NOT NULL AND schema_heads_sha256 IS NOT NULL "
            "AND runtime_layout_sha256 IS NOT NULL "
            "AND deployed_peer_set_sha256 IS NOT NULL) OR "
            "(action='controlled_restart' AND session_id IS NOT NULL "
            "AND workspace_id IS NOT NULL AND package_transaction_plan_sha256 IS NULL "
            "AND service_profile_sha256 IS NOT NULL "
            "AND candidate_verification_reference IS NOT NULL "
            "AND candidate_verification_sha256 IS NOT NULL "
            "AND candidate_slot_id IS NOT NULL AND lkg_slot_id IS NOT NULL "
            "AND candidate_slot_id!=lkg_slot_id AND schema_heads_sha256 IS NOT NULL "
            "AND runtime_layout_sha256 IS NOT NULL "
            "AND deployed_peer_set_sha256 IS NOT NULL)",
            name="ck_privileged_preparations_shape",
        ),
        sa.ForeignKeyConstraint(
            ["prepare_operation_id"],
            ["operations.operation_id"],
            name="fk_privileged_preparations_operation",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["development_sessions.session_id"],
            name="fk_privileged_preparations_session",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["registered_workspaces.workspace_id"],
            name="fk_privileged_preparations_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["consumed_by_operation_id"],
            ["operations.operation_id"],
            name="fk_privileged_preparations_consumer",
        ),
        sa.PrimaryKeyConstraint(
            "prepare_operation_id",
            name="pk_privileged_preparations",
        ),
        sa.UniqueConstraint(
            "prepared_evidence_sha256",
            name="uq_privileged_preparations_evidence",
        ),
        sa.UniqueConstraint(
            "execution_nonce_sha256",
            name="uq_privileged_preparations_nonce",
        ),
        sa.UniqueConstraint(
            "consumed_by_operation_id",
            name="uq_privileged_preparations_consumer",
        ),
    )

    op.create_table(
        "privileged_operations",
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("prepare_operation_id", sa.String(length=160), nullable=False),
        sa.Column("session_id", sa.String(length=160), nullable=True),
        sa.Column("workspace_id", sa.String(length=160), nullable=True),
        sa.Column("workspace_fence_version", sa.Integer(), nullable=True),
        sa.Column("reservation_generation", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("maximum_effect", sa.String(length=32), nullable=False),
        sa.Column("target_profile_id", sa.String(length=96), nullable=False),
        sa.Column("target_profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("broker_profile_id", sa.String(length=96), nullable=False),
        sa.Column("broker_profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("prepared_evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("current_state_binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("policy_decision_id", sa.String(length=160), nullable=False),
        sa.Column("policy_evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("ticket_id", sa.String(length=160), nullable=False),
        sa.Column("ticket_sha256", sa.String(length=64), nullable=False),
        sa.Column("ticket_nonce_sha256", sa.String(length=64), nullable=False),
        sa.Column("ticket_issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ticket_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("broker_acceptance_state", sa.String(length=24), nullable=False),
        sa.Column("broker_evidence_generation", sa.Integer(), nullable=False),
        sa.Column("broker_acceptance_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("package_transaction_plan_sha256", sa.String(length=64), nullable=True),
        sa.Column("service_profile_sha256", sa.String(length=64), nullable=True),
        sa.Column("candidate_verification_reference", sa.String(length=160), nullable=True),
        sa.Column("candidate_verification_sha256", sa.String(length=64), nullable=True),
        sa.Column("candidate_slot_id", sa.String(length=160), nullable=True),
        sa.Column("lkg_slot_id", sa.String(length=160), nullable=True),
        sa.Column("restart_checkpoint_sha256", sa.String(length=64), nullable=True),
        sa.Column("schema_heads_sha256", sa.String(length=64), nullable=True),
        sa.Column("runtime_layout_sha256", sa.String(length=64), nullable=True),
        sa.Column("deployed_peer_set_sha256", sa.String(length=64), nullable=True),
        sa.Column("candidate_outcome", sa.String(length=24), nullable=False),
        sa.Column("rollback_outcome", sa.String(length=24), nullable=False),
        sa.Column("broker_closure_state", sa.String(length=24), nullable=False),
        sa.Column("broker_closure_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("audit_closure_state", sa.String(length=24), nullable=False),
        sa.Column("audit_closure_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("fence_closure_state", sa.String(length=16), nullable=False),
        sa.Column("fence_release_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("broker_decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"action IN {_ACTIONS}", name="ck_privileged_operations_action"),
        sa.CheckConstraint(
            f"maximum_effect IN {_MAXIMUM_EFFECTS} AND "
            "((action='package_install' AND maximum_effect='package_change') OR "
            "(action='service_restart' AND maximum_effect='service_restart') OR "
            "(action='controlled_restart' AND maximum_effect='controlled_restart'))",
            name="ck_privileged_operations_effect",
        ),
        sa.CheckConstraint(
            "(workspace_fence_version IS NULL OR workspace_fence_version>=1) "
            "AND reservation_generation>=1 AND broker_evidence_generation>=0 "
            "AND updated_at>=created_at AND ticket_issued_at>=created_at "
            "AND ticket_expires_at>ticket_issued_at "
            "AND (broker_decided_at IS NULL OR broker_decided_at>=created_at) "
            "AND (closed_at IS NULL OR closed_at>=created_at) "
            "AND (last_reconciled_at IS NULL OR last_reconciled_at>=created_at)",
            name="ck_privileged_operations_generations",
        ),
        sa.CheckConstraint(
            _digests(
                "target_profile_sha256",
                "broker_profile_sha256",
                "prepared_evidence_sha256",
                "current_state_binding_sha256",
                "policy_evidence_sha256",
                "ticket_sha256",
                "ticket_nonce_sha256",
            )
            + " AND "
            + _optional_digests(
                "broker_acceptance_evidence_sha256",
                "package_transaction_plan_sha256",
                "service_profile_sha256",
                "candidate_verification_sha256",
                "restart_checkpoint_sha256",
                "schema_heads_sha256",
                "runtime_layout_sha256",
                "deployed_peer_set_sha256",
                "broker_closure_evidence_sha256",
                "audit_closure_evidence_sha256",
                "fence_release_evidence_sha256",
            ),
            name="ck_privileged_operations_digests",
        ),
        sa.CheckConstraint(
            "(broker_acceptance_state='unresolved' AND broker_evidence_generation=0 "
            "AND broker_acceptance_evidence_sha256 IS NULL AND broker_decided_at IS NULL) OR "
            "(broker_acceptance_state IN ('accepted','sealed_no_accept') "
            "AND broker_evidence_generation>=1 "
            "AND broker_acceptance_evidence_sha256 IS NOT NULL "
            "AND broker_decided_at IS NOT NULL)",
            name="ck_privileged_operations_acceptance",
        ),
        sa.CheckConstraint(
            "(state IN ('prepared','dispatched') "
            "AND broker_acceptance_state='unresolved') OR "
            "(state IN ('reconciling','uncertain','restricted_recovery') "
            "AND broker_acceptance_state='accepted') OR "
            "(state='terminal' "
            "AND broker_acceptance_state IN ('accepted','sealed_no_accept'))",
            name="ck_privileged_operations_state_acceptance",
        ),
        sa.CheckConstraint(
            "candidate_outcome IN ('not_applicable','pending','ready','failed','uncertain') "
            "AND rollback_outcome IN "
            "('not_applicable','not_started','pending','ready','failed','uncertain') "
            "AND broker_closure_state IN "
            "('pending','complete','uncertain','restricted_recovery') "
            "AND audit_closure_state IN ('pending','obligation','complete') "
            "AND fence_closure_state IN ('not_applicable','held','released') "
            "AND state IN "
            "('prepared','dispatched','reconciling','terminal','uncertain',"
            "'restricted_recovery')",
            name="ck_privileged_operations_states",
        ),
        sa.CheckConstraint(
            "(broker_closure_state='pending')=(broker_closure_evidence_sha256 IS NULL) "
            "AND (audit_closure_state='complete')=(audit_closure_evidence_sha256 IS NOT NULL) "
            "AND (fence_closure_state='released')="
            "(fence_release_evidence_sha256 IS NOT NULL)",
            name="ck_privileged_operations_closure_evidence",
        ),
        sa.CheckConstraint(
            "(action='package_install' AND session_id IS NULL AND workspace_id IS NULL "
            "AND workspace_fence_version IS NULL "
            "AND package_transaction_plan_sha256 IS NOT NULL "
            "AND service_profile_sha256 IS NULL "
            "AND candidate_verification_reference IS NULL "
            "AND candidate_verification_sha256 IS NULL AND candidate_slot_id IS NULL "
            "AND lkg_slot_id IS NULL AND restart_checkpoint_sha256 IS NULL "
            "AND schema_heads_sha256 IS NULL AND runtime_layout_sha256 IS NULL "
            "AND deployed_peer_set_sha256 IS NULL "
            "AND candidate_outcome='not_applicable' "
            "AND rollback_outcome='not_applicable' "
            "AND fence_closure_state='not_applicable') OR "
            "(action='service_restart' AND session_id IS NOT NULL AND workspace_id IS NOT NULL "
            "AND workspace_fence_version IS NOT NULL "
            "AND package_transaction_plan_sha256 IS NULL "
            "AND service_profile_sha256 IS NOT NULL "
            "AND candidate_verification_reference IS NOT NULL "
            "AND candidate_verification_sha256 IS NOT NULL AND candidate_slot_id IS NULL "
            "AND lkg_slot_id IS NOT NULL AND restart_checkpoint_sha256 IS NULL "
            "AND schema_heads_sha256 IS NOT NULL AND runtime_layout_sha256 IS NOT NULL "
            "AND deployed_peer_set_sha256 IS NOT NULL "
            "AND candidate_outcome='not_applicable' "
            "AND rollback_outcome='not_applicable' "
            "AND fence_closure_state IN ('held','released')) OR "
            "(action='controlled_restart' AND session_id IS NOT NULL "
            "AND workspace_id IS NOT NULL AND workspace_fence_version IS NOT NULL "
            "AND package_transaction_plan_sha256 IS NULL "
            "AND service_profile_sha256 IS NOT NULL "
            "AND candidate_verification_reference IS NOT NULL "
            "AND candidate_verification_sha256 IS NOT NULL "
            "AND candidate_slot_id IS NOT NULL AND lkg_slot_id IS NOT NULL "
            "AND candidate_slot_id!=lkg_slot_id "
            "AND schema_heads_sha256 IS NOT NULL AND runtime_layout_sha256 IS NOT NULL "
            "AND deployed_peer_set_sha256 IS NOT NULL "
            "AND candidate_outcome IN ('pending','ready','failed','uncertain') "
            "AND rollback_outcome IN "
            "('not_started','pending','ready','failed','uncertain') "
            "AND fence_closure_state IN ('held','released'))",
            name="ck_privileged_operations_shape",
        ),
        sa.CheckConstraint(
            "(state IN ('prepared','dispatched','reconciling') AND closed_at IS NULL) OR "
            "(state='uncertain' AND broker_closure_state='uncertain' "
            "AND broker_acceptance_state='accepted' AND closed_at IS NULL) OR "
            "(state='restricted_recovery' "
            "AND broker_closure_state='restricted_recovery' "
            "AND broker_acceptance_state='accepted' AND closed_at IS NULL) OR "
            "(state='terminal' AND broker_acceptance_state!='unresolved' "
            "AND broker_closure_state='complete' AND audit_closure_state='complete' "
            "AND fence_closure_state IN ('not_applicable','released') "
            "AND (action!='controlled_restart' OR restart_checkpoint_sha256 IS NOT NULL) "
            "AND closed_at IS NOT NULL)",
            name="ck_privileged_operations_terminal",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.operation_id"],
            name="fk_privileged_operations_operation",
        ),
        sa.ForeignKeyConstraint(
            ["prepare_operation_id"],
            ["privileged_preparations.prepare_operation_id"],
            name="fk_privileged_operations_preparation",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["development_sessions.session_id"],
            name="fk_privileged_operations_session",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["registered_workspaces.workspace_id"],
            name="fk_privileged_operations_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["policy_decision_id"],
            ["policy_decisions.policy_decision_id"],
            name="fk_privileged_operations_policy",
        ),
        sa.PrimaryKeyConstraint("operation_id", name="pk_privileged_operations"),
        sa.UniqueConstraint("prepare_operation_id", name="uq_privileged_operations_preparation"),
        sa.UniqueConstraint("ticket_id", name="uq_privileged_operations_ticket_id"),
        sa.UniqueConstraint("ticket_sha256", name="uq_privileged_operations_ticket_digest"),
        sa.UniqueConstraint("ticket_nonce_sha256", name="uq_privileged_operations_nonce"),
    )
    op.create_index(
        "ix_privileged_operations_state",
        "privileged_operations",
        ["state", "updated_at"],
        unique=False,
    )

    op.create_table(
        "privileged_effect_reservations",
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("workspace_id", sa.String(length=160), nullable=True),
        sa.Column("workspace_fence_version", sa.Integer(), nullable=True),
        sa.Column("reservation_generation", sa.Integer(), nullable=False),
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("closure_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(workspace_fence_version IS NULL OR workspace_fence_version>=1) "
            "AND reservation_generation>=1 "
            "AND updated_at>=acquired_at "
            "AND (released_at IS NULL OR released_at>=acquired_at)",
            name="ck_privileged_effect_reservations_generations",
        ),
        sa.CheckConstraint(
            "state IN ('held','released','uncertain','restricted_recovery') "
            "AND ((state='released' AND active_slot IS NULL "
            "AND released_at IS NOT NULL AND closure_evidence_sha256 IS NOT NULL) OR "
            "(state!='released' AND active_slot=1 AND released_at IS NULL "
            "AND closure_evidence_sha256 IS NULL)) "
            "AND (closure_evidence_sha256 IS NULL OR length(closure_evidence_sha256)=64)",
            name="ck_privileged_effect_reservations_state",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["privileged_operations.operation_id"],
            name="fk_privileged_effect_reservations_operation",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["registered_workspaces.workspace_id"],
            name="fk_privileged_effect_reservations_workspace",
        ),
        sa.PrimaryKeyConstraint(
            "operation_id",
            name="pk_privileged_effect_reservations",
        ),
        sa.UniqueConstraint(
            "reservation_generation",
            name="uq_privileged_effect_reservation_generation",
        ),
        sa.UniqueConstraint(
            "active_slot",
            name="uq_privileged_effect_reservation_active_slot",
        ),
    )

    for table in (
        "privileged_preparations",
        "privileged_operations",
        "privileged_effect_reservations",
    ):
        op.execute(
            f"""
            CREATE TRIGGER {table}_no_delete
            BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT, 'privileged application evidence is retained'); END
            """
        )

    _create_preparation_triggers()
    _create_operation_triggers()
    _create_reservation_triggers()

    op.execute(
        "UPDATE kernel_meta SET schema_generation=6, updated_at=CURRENT_TIMESTAMP "
        "WHERE id=1 AND schema_generation=5"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE kernel_meta SET schema_generation=5, updated_at=CURRENT_TIMESTAMP "
        "WHERE id=1 AND schema_generation=6"
    )
    op.execute("DROP TRIGGER privileged_effect_reservations_guarded_update")
    op.execute("DROP TRIGGER privileged_effect_reservations_validate_operation")
    op.execute("DROP TRIGGER privileged_operations_guarded_update")
    op.execute("DROP TRIGGER privileged_operations_validate_preparation")
    op.execute("DROP TRIGGER privileged_preparations_guarded_update")
    op.execute("DROP TRIGGER privileged_preparations_validate_operation")
    for table in (
        "privileged_effect_reservations",
        "privileged_operations",
        "privileged_preparations",
    ):
        op.execute(f"DROP TRIGGER {table}_no_delete")
    op.drop_table("privileged_effect_reservations")
    op.drop_index("ix_privileged_operations_state", table_name="privileged_operations")
    op.drop_table("privileged_operations")
    op.drop_table("privileged_preparations")


def _create_preparation_triggers() -> None:
    op.execute(
        """
        CREATE TRIGGER privileged_preparations_validate_operation
        BEFORE INSERT ON privileged_preparations
        BEGIN
          SELECT CASE WHEN NEW.state!='available'
          THEN RAISE(ABORT, 'privileged preparation must begin available') END;
          SELECT CASE WHEN NOT EXISTS (
            SELECT 1
            FROM operations operation
            JOIN policy_decisions policy ON policy.operation_id=operation.operation_id
            WHERE operation.operation_id=NEW.prepare_operation_id
              AND operation.operation_contract='privileged_prepare'
              AND operation.tool_name='privileged_prepare'
              AND operation.state='succeeded'
              AND operation.terminality='terminal'
              AND operation.effect_knowledge='known_effect'
              AND policy.decision='allow'
              AND policy.controller_id=operation.controller_id
              AND policy.controller_epoch=operation.controller_epoch
              AND policy.operation_contract=operation.operation_contract
              AND policy.operation_contract_version=operation.operation_contract_version
              AND policy.normalized_target_digest=NEW.target_profile_sha256
          ) THEN RAISE(ABORT, 'privileged preparation lacks exact no-effect authority') END;
          SELECT CASE WHEN NEW.action!='package_install' AND NOT EXISTS (
            SELECT 1
            FROM operations operation
            JOIN development_sessions session
              ON session.session_id=NEW.session_id
            WHERE operation.operation_id=NEW.prepare_operation_id
              AND session.workspace_id=NEW.workspace_id
              AND session.controller_id=operation.controller_id
              AND session.controller_epoch=operation.controller_epoch
              AND session.device_id=operation.device_id
              AND session.device_epoch=operation.device_epoch
              AND session.state='active'
              AND session.activation_closure='complete'
          ) THEN RAISE(ABORT, 'privileged preparation lacks exact active session') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER privileged_preparations_guarded_update
        BEFORE UPDATE ON privileged_preparations
        BEGIN
          SELECT CASE WHEN
            NEW.prepare_operation_id!=OLD.prepare_operation_id OR
            NEW.session_id IS NOT OLD.session_id OR NEW.workspace_id IS NOT OLD.workspace_id OR
            NEW.action!=OLD.action OR NEW.target_profile_id!=OLD.target_profile_id OR
            NEW.target_profile_sha256!=OLD.target_profile_sha256 OR
            NEW.maximum_effect!=OLD.maximum_effect OR
            NEW.normalized_request_sha256!=OLD.normalized_request_sha256 OR
            NEW.current_state_binding_sha256!=OLD.current_state_binding_sha256 OR
            NEW.prepared_evidence_sha256!=OLD.prepared_evidence_sha256 OR
            NEW.execution_nonce_sha256!=OLD.execution_nonce_sha256 OR
            NEW.package_transaction_plan_sha256 IS NOT OLD.package_transaction_plan_sha256 OR
            NEW.service_profile_sha256 IS NOT OLD.service_profile_sha256 OR
            NEW.candidate_verification_reference IS NOT OLD.candidate_verification_reference OR
            NEW.candidate_verification_sha256 IS NOT OLD.candidate_verification_sha256 OR
            NEW.candidate_slot_id IS NOT OLD.candidate_slot_id OR
            NEW.lkg_slot_id IS NOT OLD.lkg_slot_id OR
            NEW.schema_heads_sha256 IS NOT OLD.schema_heads_sha256 OR
            NEW.runtime_layout_sha256 IS NOT OLD.runtime_layout_sha256 OR
            NEW.deployed_peer_set_sha256 IS NOT OLD.deployed_peer_set_sha256 OR
            NEW.created_at!=OLD.created_at OR NEW.expires_at!=OLD.expires_at
          THEN RAISE(ABORT, 'privileged preparation identity changed') END;
          SELECT CASE WHEN NEW.updated_at<OLD.updated_at OR
            (OLD.state!='available' AND NEW.state!=OLD.state) OR
            (OLD.consumed_by_operation_id IS NOT NULL AND
             NEW.consumed_by_operation_id IS NOT OLD.consumed_by_operation_id) OR
            (OLD.consumed_at IS NOT NULL AND NEW.consumed_at IS NOT OLD.consumed_at) OR
            NOT (NEW.state=OLD.state OR
              (OLD.state='available' AND NEW.state IN ('consumed','expired')))
          THEN RAISE(ABORT, 'privileged preparation state regressed') END;
          SELECT CASE WHEN NEW.state='consumed' AND NOT EXISTS (
            SELECT 1 FROM privileged_operations privileged
            WHERE privileged.prepare_operation_id=NEW.prepare_operation_id
              AND privileged.operation_id=NEW.consumed_by_operation_id
          ) THEN RAISE(ABORT, 'privileged preparation consumer is not exact') END;
        END
        """
    )


def _create_operation_triggers() -> None:
    op.execute(
        """
        CREATE TRIGGER privileged_operations_validate_preparation
        BEFORE INSERT ON privileged_operations
        BEGIN
          SELECT CASE WHEN NOT EXISTS (
            SELECT 1 FROM privileged_preparations preparation
            WHERE preparation.prepare_operation_id=NEW.prepare_operation_id
              AND preparation.state='available'
              AND preparation.session_id IS NEW.session_id
              AND preparation.workspace_id IS NEW.workspace_id
              AND preparation.action=NEW.action
              AND preparation.target_profile_id=NEW.target_profile_id
              AND preparation.target_profile_sha256=NEW.target_profile_sha256
              AND preparation.maximum_effect=NEW.maximum_effect
              AND preparation.current_state_binding_sha256=NEW.current_state_binding_sha256
              AND preparation.prepared_evidence_sha256=NEW.prepared_evidence_sha256
              AND preparation.execution_nonce_sha256=NEW.ticket_nonce_sha256
              AND preparation.package_transaction_plan_sha256
                    IS NEW.package_transaction_plan_sha256
              AND preparation.service_profile_sha256 IS NEW.service_profile_sha256
              AND preparation.candidate_verification_reference
                    IS NEW.candidate_verification_reference
              AND preparation.candidate_verification_sha256
                    IS NEW.candidate_verification_sha256
              AND preparation.candidate_slot_id IS NEW.candidate_slot_id
              AND preparation.lkg_slot_id IS NEW.lkg_slot_id
              AND preparation.schema_heads_sha256 IS NEW.schema_heads_sha256
              AND preparation.runtime_layout_sha256 IS NEW.runtime_layout_sha256
              AND preparation.deployed_peer_set_sha256 IS NEW.deployed_peer_set_sha256
          ) THEN RAISE(ABORT, 'privileged execution does not match preparation') END;
          SELECT CASE WHEN NOT EXISTS (
            SELECT 1
            FROM operations operation
            JOIN policy_decisions policy
              ON policy.policy_decision_id=NEW.policy_decision_id
             AND policy.operation_id=operation.operation_id
            WHERE operation.operation_id=NEW.operation_id
              AND operation.state NOT IN ('received','rejected')
              AND operation.tool_name=operation.operation_contract
              AND operation.operation_contract=CASE NEW.action
                WHEN 'package_install' THEN 'package_install'
                WHEN 'service_restart' THEN 'binnacle_service_restart'
                WHEN 'controlled_restart' THEN 'binnacle_restart'
              END
              AND policy.decision='allow'
              AND policy.controller_id=operation.controller_id
              AND policy.controller_epoch=operation.controller_epoch
              AND policy.operation_contract=operation.operation_contract
              AND policy.operation_contract_version=operation.operation_contract_version
              AND policy.normalized_target_digest=NEW.target_profile_sha256
              AND policy.runtime_policy_sha256=NEW.policy_evidence_sha256
          ) THEN RAISE(ABORT, 'privileged execution lacks exact policy authority') END;
          SELECT CASE WHEN NEW.action!='package_install' AND NOT EXISTS (
            SELECT 1 FROM workspace_mutation_fences fence
            WHERE fence.workspace_id=NEW.workspace_id
              AND fence.fence_version=NEW.workspace_fence_version
              AND fence.active_operation_id=NEW.operation_id
              AND fence.active_contract=CASE NEW.action
                WHEN 'service_restart' THEN 'binnacle_service_restart'
                WHEN 'controlled_restart' THEN 'binnacle_restart'
              END
              AND fence.acquired_at IS NOT NULL
          ) THEN RAISE(ABORT, 'privileged execution lacks exact workspace fence') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER privileged_operations_guarded_update
        BEFORE UPDATE ON privileged_operations
        BEGIN
          SELECT CASE WHEN
            NEW.operation_id!=OLD.operation_id OR
            NEW.prepare_operation_id!=OLD.prepare_operation_id OR
            NEW.session_id IS NOT OLD.session_id OR NEW.workspace_id IS NOT OLD.workspace_id OR
            NEW.workspace_fence_version IS NOT OLD.workspace_fence_version OR
            NEW.reservation_generation!=OLD.reservation_generation OR
            NEW.action!=OLD.action OR NEW.maximum_effect!=OLD.maximum_effect OR
            NEW.target_profile_id!=OLD.target_profile_id OR
            NEW.target_profile_sha256!=OLD.target_profile_sha256 OR
            NEW.broker_profile_id!=OLD.broker_profile_id OR
            NEW.broker_profile_sha256!=OLD.broker_profile_sha256 OR
            NEW.prepared_evidence_sha256!=OLD.prepared_evidence_sha256 OR
            NEW.current_state_binding_sha256!=OLD.current_state_binding_sha256 OR
            NEW.policy_decision_id!=OLD.policy_decision_id OR
            NEW.policy_evidence_sha256!=OLD.policy_evidence_sha256 OR
            NEW.ticket_id!=OLD.ticket_id OR NEW.ticket_sha256!=OLD.ticket_sha256 OR
            NEW.ticket_nonce_sha256!=OLD.ticket_nonce_sha256 OR
            NEW.ticket_issued_at!=OLD.ticket_issued_at OR
            NEW.ticket_expires_at!=OLD.ticket_expires_at OR
            NEW.package_transaction_plan_sha256 IS NOT OLD.package_transaction_plan_sha256 OR
            NEW.service_profile_sha256 IS NOT OLD.service_profile_sha256 OR
            NEW.candidate_verification_reference IS NOT OLD.candidate_verification_reference OR
            NEW.candidate_verification_sha256 IS NOT OLD.candidate_verification_sha256 OR
            NEW.candidate_slot_id IS NOT OLD.candidate_slot_id OR
            NEW.lkg_slot_id IS NOT OLD.lkg_slot_id OR
            NEW.schema_heads_sha256 IS NOT OLD.schema_heads_sha256 OR
            NEW.runtime_layout_sha256 IS NOT OLD.runtime_layout_sha256 OR
            NEW.deployed_peer_set_sha256 IS NOT OLD.deployed_peer_set_sha256 OR
            NEW.created_at!=OLD.created_at
          THEN RAISE(ABORT, 'privileged operation identity changed') END;
          SELECT CASE WHEN
            NEW.broker_evidence_generation<OLD.broker_evidence_generation OR
            NEW.updated_at<OLD.updated_at OR
            (OLD.broker_acceptance_state!='unresolved' AND
             NEW.broker_acceptance_state!=OLD.broker_acceptance_state) OR
            (OLD.broker_acceptance_evidence_sha256 IS NOT NULL AND
             NEW.broker_acceptance_evidence_sha256 IS NOT
               OLD.broker_acceptance_evidence_sha256) OR
            (OLD.restart_checkpoint_sha256 IS NOT NULL AND
             NEW.restart_checkpoint_sha256 IS NOT OLD.restart_checkpoint_sha256) OR
            (OLD.broker_closure_evidence_sha256 IS NOT NULL AND
             (NEW.broker_closure_evidence_sha256 IS NULL OR
              (NEW.broker_closure_state=OLD.broker_closure_state AND
               NEW.broker_closure_evidence_sha256 IS NOT
                 OLD.broker_closure_evidence_sha256))) OR
            (OLD.audit_closure_evidence_sha256 IS NOT NULL AND
             NEW.audit_closure_evidence_sha256 IS NOT OLD.audit_closure_evidence_sha256) OR
            (OLD.fence_release_evidence_sha256 IS NOT NULL AND
             NEW.fence_release_evidence_sha256 IS NOT OLD.fence_release_evidence_sha256) OR
            (OLD.broker_decided_at IS NOT NULL AND
             NEW.broker_decided_at IS NOT OLD.broker_decided_at) OR
            (OLD.closed_at IS NOT NULL AND NEW.closed_at IS NOT OLD.closed_at) OR
            (OLD.last_reconciled_at IS NOT NULL AND
             NEW.last_reconciled_at<OLD.last_reconciled_at) OR
            NOT (NEW.candidate_outcome=OLD.candidate_outcome OR
              (OLD.candidate_outcome='pending' AND
               NEW.candidate_outcome IN ('ready','failed','uncertain')) OR
              (OLD.candidate_outcome='uncertain' AND
               NEW.candidate_outcome IN ('ready','failed'))) OR
            NOT (NEW.rollback_outcome=OLD.rollback_outcome OR
              (OLD.rollback_outcome='not_started' AND
               NEW.rollback_outcome IN ('pending','ready','failed','uncertain')) OR
              (OLD.rollback_outcome='pending' AND
               NEW.rollback_outcome IN ('ready','failed','uncertain')) OR
              (OLD.rollback_outcome='uncertain' AND
               NEW.rollback_outcome IN ('ready','failed'))) OR
            NOT (NEW.broker_closure_state=OLD.broker_closure_state OR
              (OLD.broker_closure_state='pending' AND NEW.broker_closure_state IN
               ('complete','uncertain','restricted_recovery')) OR
              (OLD.broker_closure_state='uncertain' AND
               NEW.broker_closure_state IN ('complete','restricted_recovery')) OR
              (OLD.broker_closure_state='restricted_recovery' AND
               NEW.broker_closure_state='complete')) OR
            NOT (NEW.audit_closure_state=OLD.audit_closure_state OR
              (OLD.audit_closure_state='pending' AND
               NEW.audit_closure_state IN ('obligation','complete')) OR
              (OLD.audit_closure_state='obligation' AND
               NEW.audit_closure_state='complete')) OR
            NOT (NEW.fence_closure_state=OLD.fence_closure_state OR
              (OLD.fence_closure_state='held' AND NEW.fence_closure_state='released')) OR
            NOT (NEW.state=OLD.state OR
              (OLD.state='prepared' AND NEW.state IN
               ('dispatched','terminal','uncertain','restricted_recovery')) OR
              (OLD.state='dispatched' AND NEW.state IN
               ('reconciling','terminal','uncertain','restricted_recovery')) OR
              (OLD.state='reconciling' AND NEW.state IN
               ('terminal','uncertain','restricted_recovery')) OR
              (OLD.state='uncertain' AND NEW.state IN
               ('reconciling','terminal','restricted_recovery')) OR
              (OLD.state='restricted_recovery' AND NEW.state IN
               ('reconciling','terminal')))
          THEN RAISE(ABORT, 'privileged operation evidence regressed') END;
          SELECT CASE WHEN NOT EXISTS (
            SELECT 1 FROM privileged_effect_reservations reservation
            WHERE reservation.operation_id=NEW.operation_id
              AND reservation.reservation_generation=NEW.reservation_generation
              AND reservation.state=CASE NEW.state
                WHEN 'terminal' THEN 'released'
                WHEN 'uncertain' THEN 'uncertain'
                WHEN 'restricted_recovery' THEN 'restricted_recovery'
                ELSE 'held'
              END
          ) THEN RAISE(ABORT, 'privileged operation lacks matching effect reservation') END;
        END
        """
    )


def _create_reservation_triggers() -> None:
    op.execute(
        """
        CREATE TRIGGER privileged_effect_reservations_validate_operation
        BEFORE INSERT ON privileged_effect_reservations
        BEGIN
          SELECT CASE WHEN NEW.state!='held' OR NEW.active_slot!=1
          THEN RAISE(ABORT, 'privileged effect reservation must begin held') END;
          SELECT CASE WHEN NOT EXISTS (
            SELECT 1 FROM privileged_operations privileged
            WHERE privileged.operation_id=NEW.operation_id
              AND privileged.reservation_generation=NEW.reservation_generation
              AND privileged.workspace_id IS NEW.workspace_id
              AND privileged.workspace_fence_version IS NEW.workspace_fence_version
              AND ((privileged.action='package_install' AND NEW.workspace_id IS NULL) OR
                   (privileged.action IN ('service_restart','controlled_restart') AND
                    NEW.workspace_id IS NOT NULL))
          ) THEN RAISE(ABORT, 'privileged effect reservation conflicts with operation') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER privileged_effect_reservations_guarded_update
        BEFORE UPDATE ON privileged_effect_reservations
        BEGIN
          SELECT CASE WHEN NEW.operation_id!=OLD.operation_id OR
            NEW.workspace_id IS NOT OLD.workspace_id OR
            NEW.workspace_fence_version IS NOT OLD.workspace_fence_version OR
            NEW.reservation_generation!=OLD.reservation_generation OR
            NEW.acquired_at!=OLD.acquired_at
          THEN RAISE(ABORT, 'privileged effect reservation identity changed') END;
          SELECT CASE WHEN NEW.updated_at<OLD.updated_at OR
            (OLD.closure_evidence_sha256 IS NOT NULL AND
             NEW.closure_evidence_sha256 IS NOT OLD.closure_evidence_sha256) OR
            (OLD.released_at IS NOT NULL AND NEW.released_at IS NOT OLD.released_at) OR
            NOT (NEW.state=OLD.state OR
              (OLD.state='held' AND NEW.state IN
               ('released','uncertain','restricted_recovery')) OR
              (OLD.state='uncertain' AND NEW.state IN
               ('released','restricted_recovery')) OR
              (OLD.state='restricted_recovery' AND NEW.state='released'))
          THEN RAISE(ABORT, 'privileged effect reservation evidence regressed') END;
        END
        """
    )


def _digest(column: str) -> str:
    return f"length({column})=64 AND {column} NOT GLOB '*[^0-9a-f]*'"


def _digests(*columns: str) -> str:
    return " AND ".join(_digest(column) for column in columns)


def _optional_digests(*columns: str) -> str:
    return " AND ".join(f"({column} IS NULL OR {_digest(column)})" for column in columns)
