"""Add authoritative Phase 7 command-operation correlation.

Revision ID: 0004_execution_operations
Revises: 0003_development_workspace

The application records command/ticket/cancellation facts only.  The independent executor
database has a separate migration environment and is never opened by the application.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_execution_operations"
down_revision = "0003_development_workspace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "command_operations",
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("session_id", sa.String(length=160), nullable=False),
        sa.Column("workspace_id", sa.String(length=160), nullable=False),
        sa.Column("controller_epoch", sa.Integer(), nullable=False),
        sa.Column("device_epoch", sa.Integer(), nullable=False),
        sa.Column("development_session_state_version", sa.Integer(), nullable=False),
        sa.Column("development_session_closure_sha256", sa.String(length=64), nullable=False),
        sa.Column("ticket_id", sa.String(length=160), nullable=False),
        sa.Column("ticket_sha256", sa.String(length=64), nullable=False),
        sa.Column("single_use_nonce_sha256", sa.String(length=64), nullable=False),
        sa.Column("ticket_issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ticket_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ticket_boot_id_digest", sa.String(length=64), nullable=False),
        sa.Column("ticket_monotonic_deadline_ns", sa.Integer(), nullable=False),
        sa.Column("admission_record_id", sa.String(length=160), nullable=False),
        sa.Column("command_profile_id", sa.String(length=160), nullable=False),
        sa.Column("workspace_profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("workspace_root_identity_sha256", sa.String(length=64), nullable=False),
        sa.Column("workspace_mount_identity_sha256", sa.String(length=64), nullable=False),
        sa.Column("workspace_fence_version", sa.Integer(), nullable=False),
        sa.Column("executable_identity_sha256", sa.String(length=64), nullable=False),
        sa.Column("argv_sha256", sa.String(length=64), nullable=False),
        sa.Column("cwd_sha256", sa.String(length=64), nullable=False),
        sa.Column("environment_sha256", sa.String(length=64), nullable=False),
        sa.Column("stdin_sha256", sa.String(length=64), nullable=True),
        sa.Column("stdin_reference_sha256", sa.String(length=64), nullable=True),
        sa.Column("workspace_script_sha256", sa.String(length=64), nullable=True),
        sa.Column("mount_plan_sha256", sa.String(length=64), nullable=False),
        sa.Column("policy_sha256", sa.String(length=64), nullable=False),
        sa.Column("resource_plan_sha256", sa.String(length=64), nullable=False),
        sa.Column("sandbox_plan_sha256", sa.String(length=64), nullable=False),
        sa.Column("process_isolation_plan_sha256", sa.String(length=64), nullable=False),
        sa.Column("network_plan_sha256", sa.String(length=64), nullable=False),
        sa.Column("record_version", sa.Integer(), nullable=False),
        sa.Column("acceptance_state", sa.String(length=32), nullable=False),
        sa.Column("execution_id", sa.String(length=160), nullable=True),
        sa.Column("executor_reference", sa.String(length=160), nullable=True),
        sa.Column("accepted_receipt_sha256", sa.String(length=64), nullable=True),
        sa.Column("no_accept_reference", sa.String(length=160), nullable=True),
        sa.Column("no_accept_receipt_sha256", sa.String(length=64), nullable=True),
        sa.Column("phase7_cancel_generation", sa.Integer(), nullable=False),
        sa.Column("supervisor_ack_cancel_generation", sa.Integer(), nullable=False),
        sa.Column("supervisor_cancel_disposition", sa.String(length=40), nullable=True),
        sa.Column("supervisor_evidence_generation", sa.Integer(), nullable=False),
        sa.Column("supervisor_cancel_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("last_executor_state", sa.String(length=32), nullable=True),
        sa.Column("terminal_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("descendants_stopped", sa.Boolean(), nullable=False),
        sa.Column("output_finalized", sa.Boolean(), nullable=False),
        sa.Column("private_resources_cleaned", sa.Boolean(), nullable=False),
        sa.Column("cleanup_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("closure_state", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(operation_id) BETWEEN 1 AND 160 "
            "AND length(session_id) BETWEEN 1 AND 160 "
            "AND length(workspace_id) BETWEEN 1 AND 160 "
            "AND length(ticket_id) BETWEEN 1 AND 160 "
            "AND length(admission_record_id) BETWEEN 1 AND 160 "
            "AND length(command_profile_id) BETWEEN 1 AND 160",
            name="ck_command_operations_identifiers",
        ),
        sa.CheckConstraint(
            "controller_epoch >= 1 AND device_epoch >= 1 "
            "AND development_session_state_version >= 1 "
            "AND workspace_fence_version >= 1 AND ticket_monotonic_deadline_ns >= 0 "
            "AND record_version >= 1 AND phase7_cancel_generation >= 0 "
            "AND supervisor_ack_cancel_generation >= 0 "
            "AND supervisor_ack_cancel_generation <= phase7_cancel_generation "
            "AND supervisor_evidence_generation >= 0",
            name="ck_command_operations_generations",
        ),
        sa.CheckConstraint(
            "ticket_expires_at > ticket_issued_at AND updated_at >= created_at "
            "AND (last_reconciled_at IS NULL OR last_reconciled_at >= created_at)",
            name="ck_command_operations_time_order",
        ),
        sa.CheckConstraint(
            "length(development_session_closure_sha256) = 64 "
            "AND length(ticket_sha256) = 64 AND length(single_use_nonce_sha256) = 64 "
            "AND length(ticket_boot_id_digest) = 64 "
            "AND length(workspace_profile_sha256) = 64 "
            "AND length(workspace_root_identity_sha256) = 64 "
            "AND length(workspace_mount_identity_sha256) = 64 "
            "AND length(executable_identity_sha256) = 64 AND length(argv_sha256) = 64 "
            "AND length(cwd_sha256) = 64 AND length(environment_sha256) = 64 "
            "AND (stdin_sha256 IS NULL OR length(stdin_sha256) = 64) "
            "AND (stdin_reference_sha256 IS NULL OR length(stdin_reference_sha256) = 64) "
            "AND (workspace_script_sha256 IS NULL OR length(workspace_script_sha256) = 64) "
            "AND length(mount_plan_sha256) = 64 AND length(policy_sha256) = 64 "
            "AND length(resource_plan_sha256) = 64 AND length(sandbox_plan_sha256) = 64 "
            "AND length(process_isolation_plan_sha256) = 64 "
            "AND length(network_plan_sha256) = 64 "
            "AND (accepted_receipt_sha256 IS NULL OR length(accepted_receipt_sha256) = 64) "
            "AND (no_accept_receipt_sha256 IS NULL OR length(no_accept_receipt_sha256) = 64) "
            "AND (supervisor_cancel_evidence_sha256 IS NULL "
            "OR length(supervisor_cancel_evidence_sha256) = 64) "
            "AND (terminal_evidence_sha256 IS NULL OR length(terminal_evidence_sha256) = 64) "
            "AND (cleanup_evidence_sha256 IS NULL OR length(cleanup_evidence_sha256) = 64)",
            name="ck_command_operations_digests",
        ),
        sa.CheckConstraint(
            "((stdin_sha256 IS NOT NULL) + (stdin_reference_sha256 IS NOT NULL) + "
            "(workspace_script_sha256 IS NOT NULL)) <= 1",
            name="ck_command_operations_input_source",
        ),
        sa.CheckConstraint(
            "acceptance_state IN ('unresolved','accepted_execution','no_accept_proven')",
            name="ck_command_operations_acceptance_state",
        ),
        sa.CheckConstraint(
            "(acceptance_state = 'unresolved' AND execution_id IS NULL "
            "AND executor_reference IS NULL AND accepted_receipt_sha256 IS NULL "
            "AND no_accept_reference IS NULL AND no_accept_receipt_sha256 IS NULL) OR "
            "(acceptance_state = 'accepted_execution' AND execution_id IS NOT NULL "
            "AND executor_reference IS NOT NULL AND accepted_receipt_sha256 IS NOT NULL "
            "AND no_accept_reference IS NULL AND no_accept_receipt_sha256 IS NULL) OR "
            "(acceptance_state = 'no_accept_proven' AND execution_id IS NULL "
            "AND executor_reference IS NULL AND accepted_receipt_sha256 IS NULL "
            "AND no_accept_reference IS NOT NULL AND no_accept_receipt_sha256 IS NOT NULL)",
            name="ck_command_operations_acceptance_shape",
        ),
        sa.CheckConstraint(
            "supervisor_cancel_disposition IS NULL OR supervisor_cancel_disposition IN "
            "('pending_preaccept','attached_prelaunch','signal_pending','signal_applied',"
            "'terminal_already_won','no_accept_proven','uncertain')",
            name="ck_command_operations_cancel_disposition",
        ),
        sa.CheckConstraint(
            "last_executor_state IS NULL OR last_executor_state IN "
            "('accepted','launch_preparing','launch_committed','running','cancel_requested',"
            "'cancelling','exited','cleanup_pending','closed','executor_uncertain')",
            name="ck_command_operations_executor_state",
        ),
        sa.CheckConstraint(
            "closure_state IN ('pending','complete') AND "
            "(closure_state = 'pending' OR (acceptance_state != 'unresolved' "
            "AND terminal_evidence_sha256 IS NOT NULL AND descendants_stopped = 1 "
            "AND output_finalized = 1 AND private_resources_cleaned = 1 "
            "AND cleanup_evidence_sha256 IS NOT NULL "
            "AND supervisor_ack_cancel_generation = phase7_cancel_generation))",
            name="ck_command_operations_closure_shape",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"], ["operations.operation_id"], name="fk_command_operations_operation"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["development_sessions.session_id"],
            name="fk_command_operations_session",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["registered_workspaces.workspace_id"],
            name="fk_command_operations_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["admission_record_id"],
            ["policy_decisions.policy_decision_id"],
            name="fk_command_operations_admission",
        ),
        sa.PrimaryKeyConstraint("operation_id", name="pk_command_operations"),
        sa.UniqueConstraint("admission_record_id", name="uq_command_operations_admission"),
        sa.UniqueConstraint("ticket_id", name="uq_command_operations_ticket"),
        sa.UniqueConstraint("ticket_sha256", name="uq_command_operations_ticket_digest"),
        sa.UniqueConstraint("single_use_nonce_sha256", name="uq_command_operations_nonce_digest"),
        sa.UniqueConstraint("execution_id", name="uq_command_operations_execution"),
    )
    op.create_index(
        "ix_command_operations_session",
        "command_operations",
        ["session_id", "acceptance_state"],
        unique=False,
    )
    op.create_table(
        "command_cancel_requests",
        sa.Column("cancel_operation_id", sa.String(length=160), nullable=False),
        sa.Column("command_operation_id", sa.String(length=160), nullable=False),
        sa.Column("cancel_generation", sa.Integer(), nullable=False),
        sa.Column("request_fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("cancel_generation >= 1", name="ck_command_cancel_generation"),
        sa.CheckConstraint(
            "length(request_fingerprint_sha256) = 64",
            name="ck_command_cancel_request_digest",
        ),
        sa.ForeignKeyConstraint(
            ["cancel_operation_id"],
            ["operations.operation_id"],
            name="fk_command_cancel_request_operation",
        ),
        sa.ForeignKeyConstraint(
            ["command_operation_id"],
            ["command_operations.operation_id"],
            name="fk_command_cancel_request_command",
        ),
        sa.PrimaryKeyConstraint("cancel_operation_id", name="pk_command_cancel_requests"),
        sa.UniqueConstraint(
            "command_operation_id",
            "cancel_generation",
            name="uq_command_cancel_generation",
        ),
    )
    op.execute(
        """
        CREATE TRIGGER command_operations_no_delete
        BEFORE DELETE ON command_operations
        BEGIN
          SELECT RAISE(ABORT, 'command operation identity is retained');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER command_operations_guarded_update
        BEFORE UPDATE ON command_operations
        BEGIN
          SELECT CASE WHEN
            NEW.operation_id != OLD.operation_id OR NEW.session_id != OLD.session_id OR
            NEW.workspace_id != OLD.workspace_id OR NEW.controller_epoch != OLD.controller_epoch OR
            NEW.device_epoch != OLD.device_epoch OR
            NEW.development_session_state_version != OLD.development_session_state_version OR
            NEW.development_session_closure_sha256 != OLD.development_session_closure_sha256 OR
            NEW.ticket_id != OLD.ticket_id OR NEW.ticket_sha256 != OLD.ticket_sha256 OR
            NEW.single_use_nonce_sha256 != OLD.single_use_nonce_sha256 OR
            NEW.ticket_issued_at != OLD.ticket_issued_at OR
            NEW.ticket_expires_at != OLD.ticket_expires_at OR
            NEW.ticket_boot_id_digest != OLD.ticket_boot_id_digest OR
            NEW.ticket_monotonic_deadline_ns != OLD.ticket_monotonic_deadline_ns OR
            NEW.admission_record_id != OLD.admission_record_id OR
            NEW.command_profile_id != OLD.command_profile_id OR
            NEW.workspace_profile_sha256 != OLD.workspace_profile_sha256 OR
            NEW.workspace_root_identity_sha256 != OLD.workspace_root_identity_sha256 OR
            NEW.workspace_mount_identity_sha256 != OLD.workspace_mount_identity_sha256 OR
            NEW.workspace_fence_version != OLD.workspace_fence_version OR
            NEW.executable_identity_sha256 != OLD.executable_identity_sha256 OR
            NEW.argv_sha256 != OLD.argv_sha256 OR NEW.cwd_sha256 != OLD.cwd_sha256 OR
            NEW.environment_sha256 != OLD.environment_sha256 OR
            NEW.stdin_sha256 IS NOT OLD.stdin_sha256 OR
            NEW.stdin_reference_sha256 IS NOT OLD.stdin_reference_sha256 OR
            NEW.workspace_script_sha256 IS NOT OLD.workspace_script_sha256 OR
            NEW.mount_plan_sha256 != OLD.mount_plan_sha256 OR
            NEW.policy_sha256 != OLD.policy_sha256 OR
            NEW.resource_plan_sha256 != OLD.resource_plan_sha256 OR
            NEW.sandbox_plan_sha256 != OLD.sandbox_plan_sha256 OR
            NEW.process_isolation_plan_sha256 != OLD.process_isolation_plan_sha256 OR
            NEW.network_plan_sha256 != OLD.network_plan_sha256 OR
            NEW.created_at != OLD.created_at
          THEN RAISE(ABORT, 'command operation immutable facts changed') END;
          SELECT CASE WHEN NEW.record_version != OLD.record_version + 1
            THEN RAISE(ABORT, 'command operation version is not monotonic') END;
          SELECT CASE WHEN NEW.phase7_cancel_generation < OLD.phase7_cancel_generation OR
            NEW.supervisor_ack_cancel_generation < OLD.supervisor_ack_cancel_generation OR
            NEW.supervisor_evidence_generation < OLD.supervisor_evidence_generation
            THEN RAISE(ABORT, 'command operation generation regressed') END;
          SELECT CASE WHEN OLD.acceptance_state != 'unresolved' AND
            (NEW.acceptance_state != OLD.acceptance_state OR
             NEW.execution_id IS NOT OLD.execution_id OR
             NEW.executor_reference IS NOT OLD.executor_reference OR
             NEW.accepted_receipt_sha256 IS NOT OLD.accepted_receipt_sha256 OR
             NEW.no_accept_reference IS NOT OLD.no_accept_reference OR
             NEW.no_accept_receipt_sha256 IS NOT OLD.no_accept_receipt_sha256)
            THEN RAISE(ABORT, 'command acceptance truth changed') END;
          SELECT CASE WHEN OLD.closure_state = 'complete' AND NEW.closure_state != 'complete'
            THEN RAISE(ABORT, 'command closure regressed') END;
          SELECT CASE WHEN
            (NEW.supervisor_cancel_evidence_sha256 IS NOT
                 OLD.supervisor_cancel_evidence_sha256 AND NOT (
               NEW.supervisor_cancel_evidence_sha256 IS NOT NULL AND
               NEW.supervisor_ack_cancel_generation >
                   OLD.supervisor_ack_cancel_generation AND
               NEW.supervisor_evidence_generation > OLD.supervisor_evidence_generation
             )) OR
            (OLD.terminal_evidence_sha256 IS NOT NULL AND
             NEW.terminal_evidence_sha256 IS NOT OLD.terminal_evidence_sha256) OR
            (OLD.cleanup_evidence_sha256 IS NOT NULL AND
             NEW.cleanup_evidence_sha256 IS NOT OLD.cleanup_evidence_sha256) OR
            NEW.descendants_stopped<OLD.descendants_stopped OR
            NEW.output_finalized<OLD.output_finalized OR
            NEW.private_resources_cleaned<OLD.private_resources_cleaned
            THEN RAISE(ABORT, 'command retained evidence changed') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER command_cancel_requests_no_update
        BEFORE UPDATE ON command_cancel_requests
        BEGIN SELECT RAISE(ABORT, 'command cancel request is immutable'); END
        """
    )
    op.execute(
        """
        CREATE TRIGGER command_cancel_requests_no_delete
        BEFORE DELETE ON command_cancel_requests
        BEGIN SELECT RAISE(ABORT, 'command cancel request is retained'); END
        """
    )
    op.execute(
        "UPDATE kernel_meta SET schema_generation = 4, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = 1 AND schema_generation = 3"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE kernel_meta SET schema_generation = 3, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = 1 AND schema_generation = 4"
    )
    op.execute("DROP TRIGGER command_operations_guarded_update")
    op.execute("DROP TRIGGER command_operations_no_delete")
    op.execute("DROP TRIGGER command_cancel_requests_no_delete")
    op.execute("DROP TRIGGER command_cancel_requests_no_update")
    op.drop_table("command_cancel_requests")
    op.drop_index("ix_command_operations_session", table_name="command_operations")
    op.drop_table("command_operations")
