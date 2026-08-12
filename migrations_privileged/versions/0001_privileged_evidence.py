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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
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
            + ")",
            name="ck_privileged_bindings_digests",
        ),
        sa.CheckConstraint(
            "expires_at>created_at AND updated_at>=created_at AND evidence_generation>=0",
            name="ck_privileged_bindings_time",
        ),
        sa.CheckConstraint(
            "(acceptance_state='unresolved' AND evidence_generation=0 "
            "AND acceptance_evidence_sha256 IS NULL AND accepted_at IS NULL "
            "AND sealed_at IS NULL) OR "
            "(acceptance_state='accepted' AND evidence_generation>=1 "
            "AND acceptance_evidence_sha256 IS NOT NULL AND accepted_at IS NOT NULL "
            "AND sealed_at IS NULL) OR "
            "(acceptance_state='sealed_no_accept' AND evidence_generation>=1 "
            "AND acceptance_evidence_sha256 IS NOT NULL AND accepted_at IS NULL "
            "AND sealed_at IS NOT NULL)",
            name="ck_privileged_bindings_acceptance",
        ),
        sa.PrimaryKeyConstraint("operation_id", name="pk_privileged_operation_bindings"),
        sa.UniqueConstraint("ticket_id", name="uq_privileged_binding_ticket_id"),
        sa.UniqueConstraint("ticket_sha256", name="uq_privileged_binding_ticket_digest"),
        sa.UniqueConstraint("ticket_nonce_sha256", name="uq_privileged_binding_nonce"),
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
            "AND started_at IS NULL AND closed_at IS NULL) OR "
            "(state IN ('started','reconciling') AND effect_knowledge='known_effect' "
            "AND started_at IS NOT NULL AND closed_at IS NULL) OR "
            "(state='terminal' AND effect_knowledge IN "
            "('known_no_subeffect','known_effect') AND closed_at IS NOT NULL "
            "AND result_evidence_sha256 IS NOT NULL) OR "
            "(state IN ('uncertain','restricted_recovery') "
            "AND effect_knowledge='uncertain' AND started_at IS NOT NULL)",
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


def downgrade() -> None:
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
            "privileged_evidence_events",
        )
    ):
        op.execute(f"DROP TRIGGER {table}_no_delete")
    op.drop_table("privileged_evidence_events")
    op.drop_index("uq_privileged_active_subeffect", table_name="privileged_subeffects")
    op.drop_table("privileged_subeffects")
    op.drop_table("privileged_no_accept_tombstones")
    op.drop_table("privileged_operation_bindings")
    op.drop_table("privileged_meta")


def _digest(column: str) -> str:
    return _DIGEST % (column, column)
