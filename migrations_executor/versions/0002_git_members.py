"""Reserve discriminated Phase 8 read and consequential Git member evidence.

Revision ID: 0002_git_members
Revises: 0001_executor_evidence

The production start handlers remain disabled.  Until the Phase 8 dispatcher is promoted,
executor integrity requires these tables to remain empty.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_git_members"
down_revision = "0001_executor_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TRIGGER executor_meta_guarded_update")
    op.execute("DROP TRIGGER executor_meta_no_delete")
    with op.batch_alter_table("executor_meta", recreate="always") as batch:
        batch.drop_constraint("ck_executor_meta_generations", type_="check")
        batch.create_check_constraint(
            "ck_executor_meta_generations",
            "schema_generation BETWEEN 1 AND 2 AND evidence_generation_high_water >= 0 "
            "AND supervisor_generation >= 1 AND last_verified_recovery_generation >= 0 "
            "AND last_verified_recovery_generation <= evidence_generation_high_water",
        )

    op.create_table(
        "git_read_generations",
        sa.Column("application_generation", sa.Integer(), nullable=False),
        sa.Column("application_instance_sha256", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("accepted_high_water", sa.Integer(), nullable=False),
        sa.Column("sealed_high_water", sa.Integer(), nullable=False),
        sa.Column("outstanding_domains", sa.Integer(), nullable=False),
        sa.Column("quiescence_receipt_sha256", sa.String(length=64), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("drained_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "application_generation>=1 AND accepted_high_water>=0 "
            "AND sealed_high_water BETWEEN 0 AND accepted_high_water "
            "AND outstanding_domains>=0",
            name="ck_git_read_generations_counters",
        ),
        sa.CheckConstraint(
            "length(application_instance_sha256)=64 "
            "AND (quiescence_receipt_sha256 IS NULL "
            "OR length(quiescence_receipt_sha256)=64)",
            name="ck_git_read_generations_digests",
        ),
        sa.CheckConstraint(
            "(state='open' AND close_requested_at IS NULL AND drained_at IS NULL "
            "AND quiescence_receipt_sha256 IS NULL) OR "
            "(state='closing' AND close_requested_at IS NOT NULL AND drained_at IS NULL "
            "AND quiescence_receipt_sha256 IS NULL) OR "
            "(state='drained' AND close_requested_at IS NOT NULL AND drained_at IS NOT NULL "
            "AND drained_at>=close_requested_at AND outstanding_domains=0 "
            "AND sealed_high_water=accepted_high_water "
            "AND quiescence_receipt_sha256 IS NOT NULL)",
            name="ck_git_read_generations_state",
        ),
        sa.PrimaryKeyConstraint("application_generation", name="pk_git_read_generations"),
    )

    op.create_table(
        "git_members",
        sa.Column("member_id", sa.String(length=160), nullable=False),
        sa.Column("ticket_kind", sa.String(length=24), nullable=False),
        sa.Column("parent_identity", sa.String(length=160), nullable=False),
        sa.Column("parent_operation_id", sa.String(length=160), nullable=True),
        sa.Column("read_request_id", sa.String(length=160), nullable=True),
        sa.Column("stage_generation", sa.Integer(), nullable=True),
        sa.Column("application_generation", sa.Integer(), nullable=False),
        sa.Column("repository_profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("repository_safety_sha256", sa.String(length=64), nullable=False),
        sa.Column("git_plan_sha256", sa.String(length=64), nullable=False),
        sa.Column("operation_kind", sa.String(length=32), nullable=False),
        sa.Column("ticket_id", sa.String(length=160), nullable=False),
        sa.Column("ticket_sha256", sa.String(length=64), nullable=False),
        sa.Column("nonce_sha256", sa.String(length=64), nullable=False),
        sa.Column("acceptance_state", sa.String(length=24), nullable=False),
        sa.Column("execution_id", sa.String(length=160), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("last_evidence_generation", sa.Integer(), nullable=False),
        sa.Column("cancel_generation", sa.Integer(), nullable=False),
        sa.Column("acknowledged_cancel_generation", sa.Integer(), nullable=False),
        sa.Column("cleanup_complete", sa.Boolean(), nullable=False),
        sa.Column("cleanup_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "ticket_kind IN ('git_read','git_operation_member') "
            "AND operation_kind IN ('status','diff','branch_create','switch','commit',"
            "'fetch','pull','push')",
            name="ck_git_members_kind",
        ),
        sa.CheckConstraint(
            "((ticket_kind='git_read' AND read_request_id IS NOT NULL "
            "AND parent_operation_id IS NULL AND stage_generation IS NULL) OR "
            "(ticket_kind='git_operation_member' AND parent_operation_id IS NOT NULL "
            "AND read_request_id IS NULL AND stage_generation>=1))",
            name="ck_git_members_parent_shape",
        ),
        sa.CheckConstraint(
            "length(repository_profile_sha256)=64 "
            "AND length(repository_safety_sha256)=64 AND length(git_plan_sha256)=64 "
            "AND length(ticket_sha256)=64 AND length(nonce_sha256)=64 "
            "AND (cleanup_evidence_sha256 IS NULL OR length(cleanup_evidence_sha256)=64)",
            name="ck_git_members_digests",
        ),
        sa.CheckConstraint(
            "application_generation>=1 AND last_evidence_generation>=0 "
            "AND cancel_generation>=0 "
            "AND acknowledged_cancel_generation BETWEEN 0 AND cancel_generation "
            "AND updated_at>=created_at AND (closed_at IS NULL OR closed_at>=created_at)",
            name="ck_git_members_generations",
        ),
        sa.CheckConstraint(
            "((acceptance_state='unresolved' AND execution_id IS NULL) OR "
            "(acceptance_state='accepted' AND execution_id IS NOT NULL) OR "
            "(acceptance_state='no_accept' AND execution_id IS NULL)) "
            "AND state IN ('registered','accepted','running','cleanup_pending',"
            "'closed','uncertain') "
            "AND (state NOT IN ('closed','uncertain') OR closed_at IS NOT NULL) "
            "AND (cleanup_complete=0 OR cleanup_evidence_sha256 IS NOT NULL)",
            name="ck_git_members_state",
        ),
        sa.PrimaryKeyConstraint("member_id", name="pk_git_members"),
        sa.UniqueConstraint("ticket_id", name="uq_git_members_ticket"),
        sa.UniqueConstraint("ticket_sha256", name="uq_git_members_ticket_digest"),
        sa.UniqueConstraint("nonce_sha256", name="uq_git_members_nonce"),
        sa.UniqueConstraint("execution_id", name="uq_git_members_execution"),
        sa.UniqueConstraint(
            "parent_identity", "stage_generation", name="uq_git_members_parent_stage"
        ),
    )
    op.create_index(
        "ix_git_members_application_generation",
        "git_members",
        ["application_generation", "state"],
        unique=False,
    )

    op.create_table(
        "git_read_no_accept_tombstones",
        sa.Column("application_generation", sa.Integer(), nullable=False),
        sa.Column("read_request_id", sa.String(length=160), nullable=False),
        sa.Column("member_id", sa.String(length=160), nullable=False),
        sa.Column("ticket_sha256", sa.String(length=64), nullable=False),
        sa.Column("seal_high_water", sa.Integer(), nullable=False),
        sa.Column("receipt_sha256", sa.String(length=64), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "application_generation>=1 AND seal_high_water>=0 "
            "AND length(ticket_sha256)=64 AND length(receipt_sha256)=64 "
            "AND retain_until>=sealed_at",
            name="ck_git_read_tombstones_shape",
        ),
        sa.ForeignKeyConstraint(
            ["application_generation"],
            ["git_read_generations.application_generation"],
            name="fk_git_read_tombstones_generation",
        ),
        sa.PrimaryKeyConstraint(
            "application_generation",
            "read_request_id",
            name="pk_git_read_no_accept_tombstones",
        ),
        sa.UniqueConstraint("member_id", name="uq_git_read_tombstones_member"),
        sa.UniqueConstraint("ticket_sha256", name="uq_git_read_tombstones_ticket"),
    )

    for table in (
        "git_read_generations",
        "git_members",
        "git_read_no_accept_tombstones",
    ):
        op.execute(
            f"""
            CREATE TRIGGER {table}_no_delete
            BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT, 'Git executor evidence is retained'); END
            """
        )
    op.execute(
        """
        CREATE TRIGGER git_read_generations_guarded_update
        BEFORE UPDATE ON git_read_generations
        BEGIN
          SELECT CASE WHEN
            NEW.application_generation!=OLD.application_generation OR
            NEW.application_instance_sha256!=OLD.application_instance_sha256 OR
            NEW.opened_at!=OLD.opened_at OR
            NEW.accepted_high_water<OLD.accepted_high_water OR
            NEW.sealed_high_water<OLD.sealed_high_water OR
            (OLD.state='drained' AND NEW.state!='drained')
          THEN RAISE(ABORT, 'Git read generation evidence regressed') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER git_members_guarded_update
        BEFORE UPDATE ON git_members
        BEGIN
          SELECT CASE WHEN
            NEW.member_id!=OLD.member_id OR NEW.ticket_kind!=OLD.ticket_kind OR
            NEW.parent_identity!=OLD.parent_identity OR
            NEW.parent_operation_id IS NOT OLD.parent_operation_id OR
            NEW.read_request_id IS NOT OLD.read_request_id OR
            NEW.stage_generation IS NOT OLD.stage_generation OR
            NEW.application_generation!=OLD.application_generation OR
            NEW.repository_profile_sha256!=OLD.repository_profile_sha256 OR
            NEW.repository_safety_sha256!=OLD.repository_safety_sha256 OR
            NEW.git_plan_sha256!=OLD.git_plan_sha256 OR
            NEW.operation_kind!=OLD.operation_kind OR NEW.ticket_id!=OLD.ticket_id OR
            NEW.ticket_sha256!=OLD.ticket_sha256 OR NEW.nonce_sha256!=OLD.nonce_sha256 OR
            NEW.created_at!=OLD.created_at
          THEN RAISE(ABORT, 'Git member immutable facts changed') END;
          SELECT CASE WHEN
            NEW.last_evidence_generation<OLD.last_evidence_generation OR
            NEW.cancel_generation<OLD.cancel_generation OR
            NEW.acknowledged_cancel_generation<OLD.acknowledged_cancel_generation OR
            NEW.cleanup_complete<OLD.cleanup_complete OR NEW.updated_at<OLD.updated_at OR
            (OLD.state IN ('closed','uncertain') AND NEW.state!=OLD.state)
          THEN RAISE(ABORT, 'Git member evidence regressed') END;
        END
        """
    )
    op.execute(
        "UPDATE executor_meta SET schema_generation=2, updated_at=CURRENT_TIMESTAMP "
        "WHERE id=1 AND schema_generation=1"
    )
    _create_executor_meta_triggers()


def downgrade() -> None:
    op.execute("DROP TRIGGER executor_meta_guarded_update")
    op.execute("DROP TRIGGER executor_meta_no_delete")
    op.execute(
        "UPDATE executor_meta SET schema_generation=1, updated_at=CURRENT_TIMESTAMP "
        "WHERE id=1 AND schema_generation=2"
    )
    op.execute("DROP TRIGGER git_members_guarded_update")
    op.execute("DROP TRIGGER git_read_generations_guarded_update")
    for table in (
        "git_read_no_accept_tombstones",
        "git_members",
        "git_read_generations",
    ):
        op.execute(f"DROP TRIGGER {table}_no_delete")
    op.drop_table("git_read_no_accept_tombstones")
    op.drop_index("ix_git_members_application_generation", table_name="git_members")
    op.drop_table("git_members")
    op.drop_table("git_read_generations")
    with op.batch_alter_table("executor_meta", recreate="always") as batch:
        batch.drop_constraint("ck_executor_meta_generations", type_="check")
        batch.create_check_constraint(
            "ck_executor_meta_generations",
            "schema_generation = 1 AND evidence_generation_high_water >= 0 "
            "AND supervisor_generation >= 1 AND last_verified_recovery_generation >= 0 "
            "AND last_verified_recovery_generation <= evidence_generation_high_water",
        )
    _create_executor_meta_triggers()


def _create_executor_meta_triggers() -> None:
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
    op.execute(
        """
        CREATE TRIGGER executor_meta_no_delete
        BEFORE DELETE ON executor_meta
        BEGIN SELECT RAISE(ABORT, 'executor_meta is retained'); END
        """
    )
