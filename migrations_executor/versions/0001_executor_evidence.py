"""Create the independent Phase 7 executor evidence store.

Revision ID: 0001_executor_evidence
Revises: None
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_executor_evidence"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "executor_meta",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("schema_generation", sa.Integer(), nullable=False),
        sa.Column("evidence_generation_high_water", sa.Integer(), nullable=False),
        sa.Column("supervisor_instance_id", sa.String(length=160), nullable=False),
        sa.Column("supervisor_generation", sa.Integer(), nullable=False),
        sa.Column("boot_id_digest", sa.String(length=64), nullable=False),
        sa.Column("protocol_version", sa.String(length=32), nullable=False),
        sa.Column("build_sha256", sa.String(length=64), nullable=False),
        sa.Column("profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("readiness", sa.String(length=24), nullable=False),
        sa.Column("last_verified_recovery_generation", sa.Integer(), nullable=False),
        sa.Column("failure_reason", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_executor_meta_singleton"),
        sa.CheckConstraint(
            "schema_generation = 1 AND evidence_generation_high_water >= 0 "
            "AND supervisor_generation >= 1 AND last_verified_recovery_generation >= 0 "
            "AND last_verified_recovery_generation <= evidence_generation_high_water",
            name="ck_executor_meta_generations",
        ),
        sa.CheckConstraint(
            "length(boot_id_digest) = 64 AND length(build_sha256) = 64 "
            "AND length(profile_sha256) = 64",
            name="ck_executor_meta_digests",
        ),
        sa.CheckConstraint(
            "readiness IN ('uninitialized','recovering','ready','integrity_failed')",
            name="ck_executor_meta_readiness",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_executor_meta"),
    )
    op.execute(
        "INSERT INTO executor_meta (id, schema_generation, evidence_generation_high_water, "
        "supervisor_instance_id, supervisor_generation, boot_id_digest, protocol_version, "
        "build_sha256, profile_sha256, readiness, last_verified_recovery_generation, "
        "failure_reason, created_at, updated_at) VALUES "
        "(1, 1, 0, 'uninitialized', 1, '"
        + "0" * 64
        + "', '1.0', '"
        + "0" * 64
        + "', '"
        + "0" * 64
        + "', 'uninitialized', 0, NULL, CURRENT_TIMESTAMP, "
        "CURRENT_TIMESTAMP)"
    )
    op.create_table(
        "execution_records",
        sa.Column("execution_id", sa.String(length=160), nullable=False),
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("ticket_id", sa.String(length=160), nullable=False),
        sa.Column("ticket_sha256", sa.String(length=64), nullable=False),
        sa.Column("nonce_sha256", sa.String(length=64), nullable=False),
        sa.Column("boot_id_digest", sa.String(length=64), nullable=False),
        sa.Column("ticket_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("monotonic_deadline_ns", sa.Integer(), nullable=False),
        sa.Column("ticket_correlation_sha256", sa.String(length=64), nullable=False),
        sa.Column("launch_spec_json", sa.Text(), nullable=False),
        sa.Column("launch_spec_bytes", sa.Integer(), nullable=False),
        sa.Column("launch_spec_sha256", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("last_evidence_generation", sa.Integer(), nullable=False),
        sa.Column("accepted_evidence_generation", sa.Integer(), nullable=False),
        sa.Column("accepted_executor_reference", sa.String(length=160), nullable=False),
        sa.Column("accepted_receipt_sha256", sa.String(length=64), nullable=False),
        sa.Column("effective_cancel_generation", sa.Integer(), nullable=False),
        sa.Column("acknowledged_cancel_generation", sa.Integer(), nullable=False),
        sa.Column("cancel_disposition", sa.String(length=40), nullable=True),
        sa.Column("launch_generation", sa.Integer(), nullable=False),
        sa.Column("launch_committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("backend_reference", sa.String(length=160), nullable=True),
        sa.Column("backend_domain_identity_sha256", sa.String(length=64), nullable=True),
        sa.Column("create_receipt_disposition", sa.String(length=24), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("exit_signal", sa.Integer(), nullable=True),
        sa.Column("terminal_reason", sa.String(length=160), nullable=True),
        sa.Column("terminal_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("descendants_stopped", sa.Boolean(), nullable=False),
        sa.Column("output_finalized", sa.Boolean(), nullable=False),
        sa.Column("cleanup_complete", sa.Boolean(), nullable=False),
        sa.Column("cleanup_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(ticket_sha256) = 64 AND length(nonce_sha256) = 64 "
            "AND length(boot_id_digest) = 64 AND length(ticket_correlation_sha256) = 64 "
            "AND length(launch_spec_sha256) = 64 "
            "AND length(accepted_executor_reference) BETWEEN 1 AND 160 "
            "AND length(accepted_receipt_sha256) = 64 "
            "AND (backend_domain_identity_sha256 IS NULL "
            "OR length(backend_domain_identity_sha256) = 64) "
            "AND (terminal_evidence_sha256 IS NULL OR length(terminal_evidence_sha256) = 64) "
            "AND (cleanup_evidence_sha256 IS NULL OR length(cleanup_evidence_sha256) = 64)",
            name="ck_execution_records_digests",
        ),
        sa.CheckConstraint(
            "ticket_expires_at > accepted_at AND monotonic_deadline_ns >= 0 "
            "AND launch_spec_bytes BETWEEN 2 AND 1048576 "
            "AND state_version >= 1 AND last_evidence_generation >= 1 "
            "AND accepted_evidence_generation >= 1 "
            "AND accepted_evidence_generation <= last_evidence_generation "
            "AND effective_cancel_generation >= 0 "
            "AND acknowledged_cancel_generation BETWEEN 0 AND effective_cancel_generation "
            "AND launch_generation >= 0 AND updated_at >= accepted_at",
            name="ck_execution_records_generations",
        ),
        sa.CheckConstraint(
            "state IN ('accepted','launch_preparing','launch_committed','running',"
            "'cancel_requested','cancelling','exited','cleanup_pending','closed',"
            "'executor_uncertain')",
            name="ck_execution_records_state",
        ),
        sa.CheckConstraint(
            "cancel_disposition IS NULL OR cancel_disposition IN "
            "('pending_preaccept','attached_prelaunch','signal_pending','signal_applied',"
            "'terminal_already_won','no_accept_proven','uncertain')",
            name="ck_execution_records_cancel_disposition",
        ),
        sa.CheckConstraint(
            "create_receipt_disposition IN "
            "('not_attempted','committed_pending','domain_created','no_domain','ambiguous')",
            name="ck_execution_records_create_receipt",
        ),
        sa.CheckConstraint(
            "(launch_generation = 0 AND launch_committed_at IS NULL "
            "AND create_receipt_disposition = 'not_attempted') OR "
            "(launch_generation >= 1 AND launch_committed_at IS NOT NULL "
            "AND create_receipt_disposition != 'not_attempted')",
            name="ck_execution_records_launch_shape",
        ),
        sa.CheckConstraint(
            "(create_receipt_disposition != 'domain_created') OR "
            "(backend_reference IS NOT NULL AND backend_domain_identity_sha256 IS NOT NULL)",
            name="ck_execution_records_domain_shape",
        ),
        sa.CheckConstraint(
            "(state NOT IN ('exited','cleanup_pending','closed') "
            "AND exit_code IS NULL AND exit_signal IS NULL AND terminal_reason IS NULL "
            "AND terminal_evidence_sha256 IS NULL) OR "
            "(state IN ('exited','cleanup_pending','closed') "
            "AND (exit_code IS NOT NULL OR exit_signal IS NOT NULL OR terminal_reason IS NOT NULL) "
            "AND terminal_evidence_sha256 IS NOT NULL)",
            name="ck_execution_records_terminal_shape",
        ),
        sa.CheckConstraint(
            "state != 'closed' OR (descendants_stopped = 1 AND output_finalized = 1 "
            "AND cleanup_complete = 1 AND cleanup_evidence_sha256 IS NOT NULL)",
            name="ck_execution_records_closure_shape",
        ),
        sa.PrimaryKeyConstraint("execution_id", name="pk_execution_records"),
        sa.UniqueConstraint("operation_id", name="uq_execution_records_operation"),
        sa.UniqueConstraint("ticket_id", name="uq_execution_records_ticket"),
        sa.UniqueConstraint("ticket_sha256", name="uq_execution_records_ticket_digest"),
        sa.UniqueConstraint("nonce_sha256", name="uq_execution_records_nonce"),
    )
    op.create_table(
        "pending_cancel_intents",
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("ticket_id", sa.String(length=160), nullable=False),
        sa.Column("ticket_sha256", sa.String(length=64), nullable=False),
        sa.Column("nonce_sha256", sa.String(length=64), nullable=False),
        sa.Column("boot_id_digest", sa.String(length=64), nullable=False),
        sa.Column("ticket_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("monotonic_deadline_ns", sa.Integer(), nullable=False),
        sa.Column("cancel_generation", sa.Integer(), nullable=False),
        sa.Column("last_evidence_generation", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(ticket_sha256) = 64 AND length(nonce_sha256) = 64 "
            "AND length(boot_id_digest) = 64",
            name="ck_pending_cancel_digests",
        ),
        sa.CheckConstraint(
            "cancel_generation >= 1 AND last_evidence_generation >= 1 "
            "AND monotonic_deadline_ns >= 0 AND ticket_expires_at > created_at "
            "AND updated_at >= created_at",
            name="ck_pending_cancel_generations",
        ),
        sa.PrimaryKeyConstraint("operation_id", name="pk_pending_cancel_intents"),
        sa.UniqueConstraint("ticket_id", name="uq_pending_cancel_ticket"),
        sa.UniqueConstraint("ticket_sha256", name="uq_pending_cancel_ticket_digest"),
        sa.UniqueConstraint("nonce_sha256", name="uq_pending_cancel_nonce"),
    )
    op.create_table(
        "no_accept_tombstones",
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("ticket_id", sa.String(length=160), nullable=False),
        sa.Column("ticket_sha256", sa.String(length=64), nullable=False),
        sa.Column("nonce_sha256", sa.String(length=64), nullable=False),
        sa.Column("boot_id_digest", sa.String(length=64), nullable=False),
        sa.Column("ticket_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("monotonic_deadline_ns", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=160), nullable=False),
        sa.Column("sealed_cancel_generation", sa.Integer(), nullable=False),
        sa.Column("closed_cancel_generation", sa.Integer(), nullable=False),
        sa.Column("last_evidence_generation", sa.Integer(), nullable=False),
        sa.Column("seal_reference", sa.String(length=160), nullable=False),
        sa.Column("receipt_sha256", sa.String(length=64), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(ticket_sha256) = 64 AND length(nonce_sha256) = 64 "
            "AND length(boot_id_digest) = 64 AND length(receipt_sha256) = 64",
            name="ck_no_accept_digests",
        ),
        sa.CheckConstraint(
            "sealed_cancel_generation >= 0 "
            "AND closed_cancel_generation >= sealed_cancel_generation "
            "AND last_evidence_generation >= 1 "
            "AND monotonic_deadline_ns >= 0 AND retain_until >= sealed_at "
            "AND retain_until >= ticket_expires_at",
            name="ck_no_accept_generations",
        ),
        sa.PrimaryKeyConstraint("operation_id", name="pk_no_accept_tombstones"),
        sa.UniqueConstraint("ticket_id", name="uq_no_accept_ticket"),
        sa.UniqueConstraint("ticket_sha256", name="uq_no_accept_ticket_digest"),
        sa.UniqueConstraint("nonce_sha256", name="uq_no_accept_nonce"),
        sa.UniqueConstraint("seal_reference", name="uq_no_accept_reference"),
    )
    op.create_table(
        "execution_streams",
        sa.Column("execution_id", sa.String(length=160), nullable=False),
        sa.Column("stream", sa.String(length=8), nullable=False),
        sa.Column("relative_path", sa.String(length=512), nullable=False),
        sa.Column("observed_bytes", sa.Integer(), nullable=False),
        sa.Column("retained_bytes", sa.Integer(), nullable=False),
        sa.Column("stream_sha256", sa.String(length=64), nullable=True),
        sa.Column("availability", sa.String(length=16), nullable=False),
        sa.Column("finalized", sa.Boolean(), nullable=False),
        sa.Column("last_evidence_generation", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("stream IN ('stdout','stderr')", name="ck_execution_streams_stream"),
        sa.CheckConstraint(
            "observed_bytes >= retained_bytes AND retained_bytes >= 0 "
            "AND last_evidence_generation >= 1",
            name="ck_execution_streams_bytes",
        ),
        sa.CheckConstraint(
            "availability IN ('available','truncated','expired')",
            name="ck_execution_streams_availability",
        ),
        sa.CheckConstraint(
            "stream_sha256 IS NULL OR length(stream_sha256) = 64",
            name="ck_execution_streams_digest",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["execution_records.execution_id"],
            name="fk_execution_streams_execution",
        ),
        sa.PrimaryKeyConstraint("execution_id", "stream", name="pk_execution_streams"),
    )
    op.create_table(
        "executor_evidence_events",
        sa.Column("evidence_generation", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=160), nullable=False),
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("ticket_id", sa.String(length=160), nullable=False),
        sa.Column("execution_id", sa.String(length=160), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("from_state", sa.String(length=32), nullable=True),
        sa.Column("to_state", sa.String(length=32), nullable=True),
        sa.Column("reason", sa.String(length=160), nullable=False),
        sa.Column("event_sha256", sa.String(length=64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("evidence_generation >= 1", name="ck_executor_events_generation"),
        sa.CheckConstraint("length(event_sha256) = 64", name="ck_executor_events_digest"),
        sa.PrimaryKeyConstraint("evidence_generation", name="pk_executor_evidence_events"),
        sa.UniqueConstraint("event_id", name="uq_executor_evidence_event_id"),
    )
    op.execute(
        """
        CREATE TRIGGER execution_records_guarded_update
        BEFORE UPDATE ON execution_records
        BEGIN
          SELECT CASE WHEN
            NEW.execution_id!=OLD.execution_id OR NEW.operation_id!=OLD.operation_id OR
            NEW.ticket_id!=OLD.ticket_id OR NEW.ticket_sha256!=OLD.ticket_sha256 OR
            NEW.nonce_sha256!=OLD.nonce_sha256 OR NEW.boot_id_digest!=OLD.boot_id_digest OR
            NEW.ticket_expires_at!=OLD.ticket_expires_at OR
            NEW.monotonic_deadline_ns!=OLD.monotonic_deadline_ns OR
            NEW.ticket_correlation_sha256!=OLD.ticket_correlation_sha256 OR
            NEW.launch_spec_json!=OLD.launch_spec_json OR
            NEW.launch_spec_bytes!=OLD.launch_spec_bytes OR
            NEW.launch_spec_sha256!=OLD.launch_spec_sha256 OR
            NEW.accepted_evidence_generation!=OLD.accepted_evidence_generation OR
            NEW.accepted_executor_reference!=OLD.accepted_executor_reference OR
            NEW.accepted_receipt_sha256!=OLD.accepted_receipt_sha256 OR
            NEW.accepted_at!=OLD.accepted_at
          THEN RAISE(ABORT, 'execution immutable identity changed') END;
          SELECT CASE WHEN NEW.state_version<OLD.state_version OR
            NEW.state_version>OLD.state_version+1 OR
            (NEW.state!=OLD.state AND NEW.state_version!=OLD.state_version+1) OR
            (NEW.state=OLD.state AND NEW.state_version!=OLD.state_version) OR
            NEW.last_evidence_generation<OLD.last_evidence_generation OR
            NEW.effective_cancel_generation<OLD.effective_cancel_generation OR
            NEW.acknowledged_cancel_generation<OLD.acknowledged_cancel_generation OR
            NEW.launch_generation<OLD.launch_generation OR
            NEW.descendants_stopped<OLD.descendants_stopped OR
            NEW.output_finalized<OLD.output_finalized OR
            NEW.cleanup_complete<OLD.cleanup_complete
          THEN RAISE(ABORT, 'execution evidence regressed') END;
          SELECT CASE WHEN
            (OLD.backend_reference IS NOT NULL AND
             NEW.backend_reference IS NOT OLD.backend_reference) OR
            (OLD.backend_domain_identity_sha256 IS NOT NULL AND
             NEW.backend_domain_identity_sha256 IS NOT OLD.backend_domain_identity_sha256) OR
            (OLD.exit_code IS NOT NULL AND NEW.exit_code IS NOT OLD.exit_code) OR
            (OLD.exit_signal IS NOT NULL AND NEW.exit_signal IS NOT OLD.exit_signal) OR
            (OLD.terminal_reason IS NOT NULL AND
             NEW.terminal_reason IS NOT OLD.terminal_reason) OR
            (OLD.terminal_evidence_sha256 IS NOT NULL AND
             NEW.terminal_evidence_sha256 IS NOT OLD.terminal_evidence_sha256) OR
            (OLD.cleanup_evidence_sha256 IS NOT NULL AND
             NEW.cleanup_evidence_sha256 IS NOT OLD.cleanup_evidence_sha256)
          THEN RAISE(ABORT, 'execution retained evidence changed') END;
          SELECT CASE WHEN NOT (
            NEW.create_receipt_disposition=OLD.create_receipt_disposition OR
            (OLD.create_receipt_disposition='not_attempted' AND
             NEW.create_receipt_disposition='committed_pending') OR
            (OLD.create_receipt_disposition='committed_pending' AND
             NEW.create_receipt_disposition IN ('domain_created','no_domain','ambiguous')) OR
            (OLD.create_receipt_disposition='ambiguous' AND
             NEW.create_receipt_disposition IN ('domain_created','no_domain'))
          ) THEN RAISE(ABORT, 'execution create receipt truth changed') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER pending_cancel_intents_guarded_update
        BEFORE UPDATE ON pending_cancel_intents
        BEGIN
          SELECT CASE WHEN
            NEW.operation_id!=OLD.operation_id OR NEW.ticket_id!=OLD.ticket_id OR
            NEW.ticket_sha256!=OLD.ticket_sha256 OR NEW.nonce_sha256!=OLD.nonce_sha256 OR
            NEW.boot_id_digest!=OLD.boot_id_digest OR
            NEW.ticket_expires_at!=OLD.ticket_expires_at OR
            NEW.monotonic_deadline_ns!=OLD.monotonic_deadline_ns OR
            NEW.created_at!=OLD.created_at OR NEW.cancel_generation<OLD.cancel_generation OR
            NEW.last_evidence_generation<OLD.last_evidence_generation OR
            NEW.updated_at<OLD.updated_at
          THEN RAISE(ABORT, 'pending cancel evidence regressed') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER no_accept_tombstones_guarded_update
        BEFORE UPDATE ON no_accept_tombstones
        BEGIN
          SELECT CASE WHEN
            NEW.operation_id!=OLD.operation_id OR NEW.ticket_id!=OLD.ticket_id OR
            NEW.ticket_sha256!=OLD.ticket_sha256 OR NEW.nonce_sha256!=OLD.nonce_sha256 OR
            NEW.boot_id_digest!=OLD.boot_id_digest OR
            NEW.ticket_expires_at!=OLD.ticket_expires_at OR
            NEW.monotonic_deadline_ns!=OLD.monotonic_deadline_ns OR
            NEW.reason!=OLD.reason OR
            NEW.sealed_cancel_generation!=OLD.sealed_cancel_generation OR
            NEW.seal_reference!=OLD.seal_reference OR
            NEW.receipt_sha256!=OLD.receipt_sha256 OR NEW.sealed_at!=OLD.sealed_at OR
            NEW.closed_cancel_generation<OLD.closed_cancel_generation OR
            NEW.last_evidence_generation<OLD.last_evidence_generation OR
            NEW.retain_until<OLD.retain_until
          THEN RAISE(ABORT, 'no-accept evidence regressed') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER execution_streams_guarded_update
        BEFORE UPDATE ON execution_streams
        BEGIN
          SELECT CASE WHEN
            NEW.execution_id!=OLD.execution_id OR NEW.stream!=OLD.stream OR
            NEW.relative_path!=OLD.relative_path OR
            NEW.observed_bytes<OLD.observed_bytes OR NEW.retained_bytes<OLD.retained_bytes OR
            NEW.last_evidence_generation<OLD.last_evidence_generation OR
            NEW.finalized<OLD.finalized OR NEW.updated_at<OLD.updated_at OR
            (OLD.stream_sha256 IS NOT NULL AND NEW.stream_sha256 IS NOT OLD.stream_sha256) OR
            (OLD.availability='expired' AND NEW.availability!='expired') OR
            (OLD.availability='truncated' AND NEW.availability='available')
          THEN RAISE(ABORT, 'executor output evidence regressed') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER executor_evidence_events_no_update
        BEFORE UPDATE ON executor_evidence_events
        BEGIN SELECT RAISE(ABORT, 'executor evidence events are immutable'); END
        """
    )
    op.execute(
        """
        CREATE TRIGGER executor_meta_guarded_update
        BEFORE UPDATE ON executor_meta
        BEGIN
          SELECT CASE WHEN NEW.id!=OLD.id OR
            NEW.schema_generation!=OLD.schema_generation OR
            NEW.created_at!=OLD.created_at OR
            NEW.evidence_generation_high_water<OLD.evidence_generation_high_water OR
            NEW.supervisor_generation<OLD.supervisor_generation OR
            NEW.last_verified_recovery_generation<OLD.last_verified_recovery_generation
          THEN RAISE(ABORT, 'executor metadata regressed') END;
        END
        """
    )
    for table in (
        "execution_records",
        "no_accept_tombstones",
        "executor_evidence_events",
        "executor_meta",
        "execution_streams",
    ):
        op.execute(
            f"""
            CREATE TRIGGER {table}_no_delete
            BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT, '{table} is retained'); END
            """
        )


def downgrade() -> None:
    op.execute("DROP TRIGGER executor_meta_guarded_update")
    op.execute("DROP TRIGGER executor_evidence_events_no_update")
    op.execute("DROP TRIGGER execution_streams_guarded_update")
    op.execute("DROP TRIGGER no_accept_tombstones_guarded_update")
    op.execute("DROP TRIGGER pending_cancel_intents_guarded_update")
    op.execute("DROP TRIGGER execution_records_guarded_update")
    for table in (
        "execution_records",
        "no_accept_tombstones",
        "executor_evidence_events",
        "executor_meta",
        "execution_streams",
    ):
        op.execute(f"DROP TRIGGER {table}_no_delete")
    op.drop_table("executor_evidence_events")
    op.drop_table("execution_streams")
    op.drop_table("no_accept_tombstones")
    op.drop_table("pending_cancel_intents")
    op.drop_table("execution_records")
    op.drop_table("executor_meta")
