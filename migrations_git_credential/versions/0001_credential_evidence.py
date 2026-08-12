"""Create isolated one-use Git credential evidence.

Revision ID: 0001_credential_evidence
Revises: None
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_credential_evidence"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credential_meta",
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
        sa.CheckConstraint("id=1", name="ck_credential_meta_singleton"),
        sa.CheckConstraint(
            "schema_generation=1 AND evidence_generation_high_water>=0 AND broker_generation>=1",
            name="ck_credential_meta_generations",
        ),
        sa.CheckConstraint(
            "length(build_sha256)=64 AND length(profile_sha256)=64",
            name="ck_credential_meta_digests",
        ),
        sa.CheckConstraint(
            "readiness IN ('uninitialized','disabled','recovering','ready','integrity_failed')",
            name="ck_credential_meta_readiness",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_credential_meta"),
    )
    zero = "0" * 64
    op.execute(
        "INSERT INTO credential_meta "
        "(id,schema_generation,evidence_generation_high_water,broker_instance_id,"
        "broker_generation,protocol_version,build_sha256,profile_sha256,readiness,"
        "failure_reason,created_at,updated_at) VALUES "
        f"(1,1,0,'uninitialized',1,'1.0','{zero}','{zero}','disabled',NULL,"
        "CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
    )

    op.create_table(
        "credential_use_tickets",
        sa.Column("ticket_id", sa.String(length=160), nullable=False),
        sa.Column("ticket_sha256", sa.String(length=64), nullable=False),
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("member_id", sa.String(length=160), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("audience_sha256", sa.String(length=64), nullable=False),
        sa.Column("credential_reference_sha256", sa.String(length=64), nullable=False),
        sa.Column("credential_generation", sa.Integer(), nullable=False),
        sa.Column("preimage_sha256", sa.String(length=64), nullable=True),
        sa.Column("destination_sha256", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consume_generation", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("retained_response", sa.LargeBinary(), nullable=True),
        sa.Column("retained_response_bytes", sa.Integer(), nullable=False),
        sa.Column("retained_response_sha256", sa.String(length=64), nullable=True),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("cleanup_complete", sa.Boolean(), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('commit_sign','repository_ssh') "
            "AND ((action='commit_sign' AND preimage_sha256 IS NOT NULL "
            "AND destination_sha256 IS NULL) OR "
            "(action='repository_ssh' AND destination_sha256 IS NOT NULL "
            "AND preimage_sha256 IS NULL))",
            name="ck_credential_tickets_action",
        ),
        sa.CheckConstraint(
            "length(ticket_sha256)=64 AND length(audience_sha256)=64 "
            "AND length(credential_reference_sha256)=64 "
            "AND (preimage_sha256 IS NULL OR length(preimage_sha256)=64) "
            "AND (destination_sha256 IS NULL OR length(destination_sha256)=64) "
            "AND (retained_response_sha256 IS NULL OR length(retained_response_sha256)=64) "
            "AND (evidence_sha256 IS NULL OR length(evidence_sha256)=64)",
            name="ck_credential_tickets_digests",
        ),
        sa.CheckConstraint(
            "credential_generation>=1 AND consume_generation>=0 "
            "AND retained_response_bytes BETWEEN 0 AND 1048576 "
            "AND expires_at>registered_at AND updated_at>=registered_at",
            name="ck_credential_tickets_generations",
        ),
        sa.CheckConstraint(
            "state IN ('registered','accepted','completed','uncertain','revoked') "
            "AND ((retained_response IS NULL AND retained_response_bytes=0 "
            "AND retained_response_sha256 IS NULL) OR "
            "(retained_response IS NOT NULL "
            "AND retained_response_bytes=length(retained_response) "
            "AND retained_response_sha256 IS NOT NULL)) "
            "AND (state='registered' OR accepted_at IS NOT NULL) "
            "AND (state!='completed' OR (completed_at IS NOT NULL "
            "AND evidence_sha256 IS NOT NULL AND cleanup_complete=1))",
            name="ck_credential_tickets_state",
        ),
        sa.PrimaryKeyConstraint("ticket_id", name="pk_credential_use_tickets"),
        sa.UniqueConstraint("ticket_sha256", name="uq_credential_ticket_digest"),
        sa.UniqueConstraint("operation_id", "member_id", "action", name="uq_credential_action"),
    )

    op.create_table(
        "credential_evidence_events",
        sa.Column("evidence_generation", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=160), nullable=False),
        sa.Column("ticket_id", sa.String(length=160), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("event_sha256", sa.String(length=64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "evidence_generation>=1 AND length(event_sha256)=64",
            name="ck_credential_events_shape",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["credential_use_tickets.ticket_id"],
            name="fk_credential_events_ticket",
        ),
        sa.PrimaryKeyConstraint("evidence_generation", name="pk_credential_evidence_events"),
        sa.UniqueConstraint("event_id", name="uq_credential_event_id"),
    )

    for table in ("credential_use_tickets", "credential_evidence_events"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_no_delete
            BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT, 'credential evidence is retained'); END
            """
        )
    op.execute(
        """
        CREATE TRIGGER credential_tickets_guarded_update
        BEFORE UPDATE ON credential_use_tickets
        BEGIN
          SELECT CASE WHEN
            NEW.ticket_id!=OLD.ticket_id OR NEW.ticket_sha256!=OLD.ticket_sha256 OR
            NEW.operation_id!=OLD.operation_id OR NEW.member_id!=OLD.member_id OR
            NEW.action!=OLD.action OR NEW.audience_sha256!=OLD.audience_sha256 OR
            NEW.credential_reference_sha256!=OLD.credential_reference_sha256 OR
            NEW.credential_generation!=OLD.credential_generation OR
            NEW.preimage_sha256 IS NOT OLD.preimage_sha256 OR
            NEW.destination_sha256 IS NOT OLD.destination_sha256 OR
            NEW.expires_at!=OLD.expires_at OR NEW.registered_at!=OLD.registered_at
          THEN RAISE(ABORT, 'credential ticket immutable facts changed') END;
          SELECT CASE WHEN NEW.consume_generation<OLD.consume_generation OR
            NEW.cleanup_complete<OLD.cleanup_complete OR NEW.updated_at<OLD.updated_at OR
            (OLD.state='registered' AND NEW.state NOT IN
             ('registered','accepted','uncertain','revoked')) OR
            (OLD.state='accepted' AND NEW.state NOT IN
             ('accepted','completed','uncertain','revoked')) OR
            (OLD.state IN ('completed','uncertain','revoked') AND NEW.state!=OLD.state) OR
            (OLD.accepted_at IS NOT NULL AND NEW.accepted_at IS NOT OLD.accepted_at) OR
            (OLD.completed_at IS NOT NULL AND NEW.completed_at IS NOT OLD.completed_at) OR
            (OLD.retained_response_sha256 IS NOT NULL AND
             (NEW.retained_response IS NOT OLD.retained_response OR
              NEW.retained_response_bytes!=OLD.retained_response_bytes OR
              NEW.retained_response_sha256 IS NOT OLD.retained_response_sha256)) OR
            (OLD.evidence_sha256 IS NOT NULL AND
             NEW.evidence_sha256 IS NOT OLD.evidence_sha256)
          THEN RAISE(ABORT, 'credential ticket evidence regressed') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER credential_evidence_events_no_update
        BEFORE UPDATE ON credential_evidence_events
        BEGIN SELECT RAISE(ABORT, 'credential event evidence is immutable'); END
        """
    )
    op.execute(
        """
        CREATE TRIGGER credential_meta_guarded_update
        BEFORE UPDATE ON credential_meta
        BEGIN
          SELECT CASE WHEN NEW.id!=OLD.id OR NEW.schema_generation!=OLD.schema_generation OR
            NEW.created_at!=OLD.created_at OR
            NEW.evidence_generation_high_water<OLD.evidence_generation_high_water OR
            NEW.broker_generation<OLD.broker_generation OR NEW.updated_at<OLD.updated_at OR
            ((NEW.broker_instance_id!=OLD.broker_instance_id OR
              NEW.protocol_version!=OLD.protocol_version OR
              NEW.build_sha256!=OLD.build_sha256 OR NEW.profile_sha256!=OLD.profile_sha256)
             AND NEW.broker_generation=OLD.broker_generation)
          THEN RAISE(ABORT, 'credential metadata regressed') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER credential_meta_no_delete
        BEFORE DELETE ON credential_meta
        BEGIN SELECT RAISE(ABORT, 'credential metadata is retained'); END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER credential_meta_no_delete")
    op.execute("DROP TRIGGER credential_meta_guarded_update")
    op.execute("DROP TRIGGER credential_evidence_events_no_update")
    op.execute("DROP TRIGGER credential_tickets_guarded_update")
    op.execute("DROP TRIGGER credential_evidence_events_no_delete")
    op.execute("DROP TRIGGER credential_use_tickets_no_delete")
    op.drop_table("credential_evidence_events")
    op.drop_table("credential_use_tickets")
    op.drop_table("credential_meta")
