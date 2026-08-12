"""Add retained Phase 8 Git parent, member, commit, and remote evidence.

Revision ID: 0005_git_operations
Revises: 0004_execution_operations

No handler is enabled by this migration.  The tables reserve the fail-closed application
authority boundary while the executor and credential broker retain separate databases.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_git_operations"
down_revision = "0004_execution_operations"
branch_labels = None
depends_on = None

_OID_ALGORITHMS = "('sha1','sha256')"
_EFFECT_KNOWLEDGE = "('none','known_no_effect','known_effect','partial','uncertain')"


def upgrade() -> None:
    op.create_table(
        "git_operations",
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("session_id", sa.String(length=160), nullable=False),
        sa.Column("workspace_id", sa.String(length=160), nullable=False),
        sa.Column("operation_kind", sa.String(length=32), nullable=False),
        sa.Column("repository_profile_id", sa.String(length=96), nullable=False),
        sa.Column("repository_profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("repository_safety_sha256", sa.String(length=64), nullable=False),
        sa.Column("repository_state_binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("workspace_fence_version", sa.Integer(), nullable=False),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.Column("destination_ref", sa.String(length=255), nullable=True),
        sa.Column("expected_old_oid_algorithm", sa.String(length=8), nullable=True),
        sa.Column("expected_old_oid_hex", sa.String(length=64), nullable=True),
        sa.Column("desired_oid_algorithm", sa.String(length=8), nullable=True),
        sa.Column("desired_oid_hex", sa.String(length=64), nullable=True),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("commit_request_sha256", sa.String(length=64), nullable=True),
        sa.Column("remote_request_sha256", sa.String(length=64), nullable=True),
        sa.Column("credential_reference_sha256", sa.String(length=64), nullable=True),
        sa.Column("current_stage_generation", sa.Integer(), nullable=False),
        sa.Column("aggregate_effect_knowledge", sa.String(length=24), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "operation_kind IN ('status','diff','branch_create','switch','commit',"
            "'fetch','pull','push')",
            name="ck_git_operations_kind",
        ),
        sa.CheckConstraint(
            "length(repository_profile_sha256)=64 "
            "AND length(repository_safety_sha256)=64 "
            "AND length(repository_state_binding_sha256)=64 "
            "AND length(request_sha256)=64 "
            "AND (commit_request_sha256 IS NULL OR length(commit_request_sha256)=64) "
            "AND (remote_request_sha256 IS NULL OR length(remote_request_sha256)=64) "
            "AND (credential_reference_sha256 IS NULL "
            "OR length(credential_reference_sha256)=64)",
            name="ck_git_operations_digests",
        ),
        sa.CheckConstraint(
            _optional_oid_shape("expected_old") + " AND " + _optional_oid_shape("desired"),
            name="ck_git_operations_oid_shape",
        ),
        sa.CheckConstraint(
            "workspace_fence_version>=1 AND current_stage_generation>=0 "
            "AND updated_at>=created_at "
            "AND (last_reconciled_at IS NULL OR last_reconciled_at>=created_at)",
            name="ck_git_operations_generations",
        ),
        sa.CheckConstraint(
            f"aggregate_effect_knowledge IN {_EFFECT_KNOWLEDGE} "
            "AND state IN ('planned','active','recovery_required','terminal') "
            "AND (state!='terminal' OR aggregate_effect_knowledge!='none')",
            name="ck_git_operations_state",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"], ["operations.operation_id"], name="fk_git_operations_operation"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["development_sessions.session_id"],
            name="fk_git_operations_session",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["registered_workspaces.workspace_id"],
            name="fk_git_operations_workspace",
        ),
        sa.PrimaryKeyConstraint("operation_id", name="pk_git_operations"),
    )
    op.create_index(
        "ix_git_operations_session",
        "git_operations",
        ["session_id", "state"],
        unique=False,
    )

    op.create_table(
        "git_operation_stages",
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("stage_generation", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.String(length=160), nullable=False),
        sa.Column("stage_kind", sa.String(length=48), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("pre_state_sha256", sa.String(length=64), nullable=False),
        sa.Column("member_ticket_id", sa.String(length=160), nullable=True),
        sa.Column("member_ticket_sha256", sa.String(length=64), nullable=True),
        sa.Column("acceptance_state", sa.String(length=24), nullable=False),
        sa.Column("execution_id", sa.String(length=160), nullable=True),
        sa.Column("crossing_state", sa.String(length=24), nullable=False),
        sa.Column("effect_knowledge", sa.String(length=24), nullable=False),
        sa.Column("before_oid_algorithm", sa.String(length=8), nullable=True),
        sa.Column("before_oid_hex", sa.String(length=64), nullable=True),
        sa.Column("after_oid_algorithm", sa.String(length=8), nullable=True),
        sa.Column("after_oid_hex", sa.String(length=64), nullable=True),
        sa.Column("cancel_generation", sa.Integer(), nullable=False),
        sa.Column("acknowledged_cancel_generation", sa.Integer(), nullable=False),
        sa.Column("executor_evidence_generation", sa.Integer(), nullable=False),
        sa.Column("cleanup_complete", sa.Boolean(), nullable=False),
        sa.Column("cleanup_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "stage_generation>=1 AND cancel_generation>=0 "
            "AND acknowledged_cancel_generation BETWEEN 0 AND cancel_generation "
            "AND executor_evidence_generation>=0 AND updated_at>=created_at "
            "AND (closed_at IS NULL OR closed_at>=created_at)",
            name="ck_git_stages_generations",
        ),
        sa.CheckConstraint(
            "length(input_sha256)=64 AND length(pre_state_sha256)=64 "
            "AND (member_ticket_sha256 IS NULL OR length(member_ticket_sha256)=64) "
            "AND (cleanup_evidence_sha256 IS NULL OR length(cleanup_evidence_sha256)=64)",
            name="ck_git_stages_digests",
        ),
        sa.CheckConstraint(
            "(member_ticket_id IS NULL)=(member_ticket_sha256 IS NULL) "
            "AND ((acceptance_state='unresolved' AND execution_id IS NULL) "
            "OR (acceptance_state='accepted' AND execution_id IS NOT NULL) "
            "OR (acceptance_state='no_accept' AND execution_id IS NULL))",
            name="ck_git_stages_acceptance",
        ),
        sa.CheckConstraint(
            "crossing_state IN ('not_crossed','start_committed','classified') "
            f"AND effect_knowledge IN {_EFFECT_KNOWLEDGE} "
            "AND state IN "
            "('planned','dispatched','running','cleanup_pending','closed','uncertain') "
            "AND (state NOT IN ('closed','uncertain') OR closed_at IS NOT NULL) "
            "AND (cleanup_complete=0 OR cleanup_evidence_sha256 IS NOT NULL) "
            "AND (acceptance_state!='no_accept' OR state='closed') "
            "AND (state!='closed' OR "
            "(acceptance_state!='unresolved' AND cleanup_complete=1 "
            "AND acknowledged_cancel_generation=cancel_generation "
            "AND ((acceptance_state='no_accept' AND crossing_state='not_crossed' "
            "AND effect_knowledge='known_no_effect') OR "
            "(acceptance_state='accepted' AND crossing_state='classified' "
            "AND effect_knowledge IN ('known_no_effect','known_effect','partial'))))) "
            "AND (state!='uncertain' OR effect_knowledge='uncertain')",
            name="ck_git_stages_state",
        ),
        sa.CheckConstraint(
            _optional_oid_shape("before") + " AND " + _optional_oid_shape("after"),
            name="ck_git_stages_oid_shape",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["git_operations.operation_id"],
            name="fk_git_stages_operation",
        ),
        sa.PrimaryKeyConstraint("operation_id", "stage_generation", name="pk_git_operation_stages"),
        sa.UniqueConstraint("member_id", name="uq_git_stages_member"),
        sa.UniqueConstraint("member_ticket_id", name="uq_git_stages_ticket"),
        sa.UniqueConstraint("execution_id", name="uq_git_stages_execution"),
    )
    op.create_index(
        "uq_git_stages_active_member",
        "git_operation_stages",
        ["operation_id"],
        unique=True,
        sqlite_where=sa.text("state IN ('dispatched','running','cleanup_pending','uncertain')"),
    )

    op.create_table(
        "git_commit_evidence",
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("commit_oid_algorithm", sa.String(length=8), nullable=False),
        sa.Column("commit_oid_hex", sa.String(length=64), nullable=False),
        sa.Column("tree_oid_algorithm", sa.String(length=8), nullable=False),
        sa.Column("tree_oid_hex", sa.String(length=64), nullable=False),
        sa.Column("parent_oid_algorithm", sa.String(length=8), nullable=False),
        sa.Column("parent_oid_hex", sa.String(length=64), nullable=False),
        sa.Column("author_sha256", sa.String(length=64), nullable=False),
        sa.Column("committer_sha256", sa.String(length=64), nullable=False),
        sa.Column("message_sha256", sa.String(length=64), nullable=False),
        sa.Column("preimage_sha256", sa.String(length=64), nullable=False),
        sa.Column("author_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committer_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signer_profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("signer_public_fingerprint", sa.String(length=160), nullable=False),
        sa.Column("signature_sha256", sa.String(length=64), nullable=False),
        sa.Column("signature_verified", sa.Boolean(), nullable=False),
        sa.Column("object_imported", sa.Boolean(), nullable=False),
        sa.Column("branch_cas_complete", sa.Boolean(), nullable=False),
        sa.Column("expected_main_index_identity_sha256", sa.String(length=64), nullable=False),
        sa.Column("expected_main_index_tree_oid_algorithm", sa.String(length=8), nullable=False),
        sa.Column("expected_main_index_tree_oid_hex", sa.String(length=64), nullable=False),
        sa.Column("expected_main_index_sha256", sa.String(length=64), nullable=False),
        sa.Column("target_main_index_tree_oid_algorithm", sa.String(length=8), nullable=False),
        sa.Column("target_main_index_tree_oid_hex", sa.String(length=64), nullable=False),
        sa.Column("target_main_index_sha256", sa.String(length=64), nullable=False),
        sa.Column("selected_worktree_snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("main_index_publication_state", sa.String(length=16), nullable=False),
        sa.Column("main_index_publication_receipt_sha256", sa.String(length=64), nullable=True),
        sa.Column("worktree_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            _required_oid_shape("commit")
            + " AND "
            + _required_oid_shape("tree")
            + " AND "
            + _required_oid_shape("parent")
            + " AND "
            + _required_oid_shape("expected_main_index_tree")
            + " AND "
            + _required_oid_shape("target_main_index_tree"),
            name="ck_git_commit_oids",
        ),
        sa.CheckConstraint(
            "length(author_sha256)=64 AND length(committer_sha256)=64 "
            "AND length(message_sha256)=64 AND length(preimage_sha256)=64 "
            "AND length(signer_profile_sha256)=64 AND length(signature_sha256)=64 "
            "AND length(expected_main_index_identity_sha256)=64 "
            "AND length(expected_main_index_sha256)=64 "
            "AND length(target_main_index_sha256)=64 "
            "AND length(selected_worktree_snapshot_sha256)=64 "
            "AND (main_index_publication_receipt_sha256 IS NULL OR "
            "length(main_index_publication_receipt_sha256)=64) "
            "AND (worktree_evidence_sha256 IS NULL OR length(worktree_evidence_sha256)=64)",
            name="ck_git_commit_digests",
        ),
        sa.CheckConstraint(
            "committer_at>=author_at AND updated_at>=created_at "
            "AND target_main_index_tree_oid_algorithm=tree_oid_algorithm "
            "AND target_main_index_tree_oid_hex=tree_oid_hex "
            "AND main_index_publication_state IN "
            "('not_required','pending','complete','uncertain') "
            "AND (branch_cas_complete=0 OR (signature_verified=1 AND object_imported=1)) "
            "AND (main_index_publication_state!='not_required' OR "
            "(branch_cas_complete=0 AND main_index_publication_receipt_sha256 IS NULL)) "
            "AND (main_index_publication_state!='pending' OR "
            "main_index_publication_receipt_sha256 IS NULL) "
            "AND (main_index_publication_state!='complete' OR "
            "(signature_verified=1 AND object_imported=1 AND branch_cas_complete=1 "
            "AND main_index_publication_receipt_sha256 IS NOT NULL "
            "AND worktree_evidence_sha256 IS NOT NULL))",
            name="ck_git_commit_publication",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["git_operations.operation_id"],
            name="fk_git_commit_operation",
        ),
        sa.PrimaryKeyConstraint("operation_id", name="pk_git_commit_evidence"),
        sa.UniqueConstraint("commit_oid_algorithm", "commit_oid_hex", name="uq_git_commit_oid"),
    )

    op.create_table(
        "git_remote_evidence",
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("remote_profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("destination_sha256", sa.String(length=64), nullable=False),
        sa.Column("outbound_closure_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_ref", sa.String(length=255), nullable=False),
        sa.Column("destination_ref", sa.String(length=255), nullable=False),
        sa.Column("expected_remote_state", sa.String(length=16), nullable=False),
        sa.Column("expected_oid_algorithm", sa.String(length=8), nullable=True),
        sa.Column("expected_oid_hex", sa.String(length=64), nullable=True),
        sa.Column("desired_oid_algorithm", sa.String(length=8), nullable=False),
        sa.Column("desired_oid_hex", sa.String(length=64), nullable=False),
        sa.Column("observed_oid_algorithm", sa.String(length=8), nullable=True),
        sa.Column("observed_oid_hex", sa.String(length=64), nullable=True),
        sa.Column("transport_state", sa.String(length=24), nullable=False),
        sa.Column("credential_use_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("remote_reconciled", sa.Boolean(), nullable=False),
        sa.Column("credential_cleanup_complete", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(remote_profile_sha256)=64 AND length(destination_sha256)=64 "
            "AND length(outbound_closure_sha256)=64 "
            "AND (credential_use_evidence_sha256 IS NULL "
            "OR length(credential_use_evidence_sha256)=64)",
            name="ck_git_remote_digests",
        ),
        sa.CheckConstraint(
            "((expected_remote_state='absent' AND expected_oid_algorithm IS NULL "
            "AND expected_oid_hex IS NULL) OR "
            "(expected_remote_state='oid' AND "
            + _required_oid_shape("expected")
            + ")) AND "
            + _required_oid_shape("desired")
            + " AND "
            + _optional_oid_shape("observed"),
            name="ck_git_remote_oids",
        ),
        sa.CheckConstraint(
            "transport_state IN ('not_started','accepted','sent','lost_response',"
            "'completed','uncertain') AND updated_at>=created_at "
            "AND (transport_state!='completed' OR "
            "(remote_reconciled=1 AND observed_oid_algorithm=desired_oid_algorithm "
            "AND observed_oid_hex=desired_oid_hex "
            "AND credential_use_evidence_sha256 IS NOT NULL "
            "AND credential_cleanup_complete=1))",
            name="ck_git_remote_state",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["git_operations.operation_id"],
            name="fk_git_remote_operation",
        ),
        sa.PrimaryKeyConstraint("operation_id", name="pk_git_remote_evidence"),
    )

    for table in (
        "git_operations",
        "git_operation_stages",
        "git_commit_evidence",
        "git_remote_evidence",
    ):
        op.execute(
            f"""
            CREATE TRIGGER {table}_no_delete
            BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT, 'Git evidence is retained'); END
            """
        )
    op.execute(
        """
        CREATE TRIGGER git_operations_guarded_update
        BEFORE UPDATE ON git_operations
        BEGIN
          SELECT CASE WHEN
            NEW.operation_id!=OLD.operation_id OR NEW.session_id!=OLD.session_id OR
            NEW.workspace_id!=OLD.workspace_id OR NEW.operation_kind!=OLD.operation_kind OR
            NEW.repository_profile_id!=OLD.repository_profile_id OR
            NEW.repository_profile_sha256!=OLD.repository_profile_sha256 OR
            NEW.repository_safety_sha256!=OLD.repository_safety_sha256 OR
            NEW.repository_state_binding_sha256!=OLD.repository_state_binding_sha256 OR
            NEW.workspace_fence_version!=OLD.workspace_fence_version OR
            NEW.source_ref IS NOT OLD.source_ref OR
            NEW.destination_ref IS NOT OLD.destination_ref OR
            NEW.expected_old_oid_algorithm IS NOT OLD.expected_old_oid_algorithm OR
            NEW.expected_old_oid_hex IS NOT OLD.expected_old_oid_hex OR
            NEW.desired_oid_algorithm IS NOT OLD.desired_oid_algorithm OR
            NEW.desired_oid_hex IS NOT OLD.desired_oid_hex OR
            NEW.request_sha256!=OLD.request_sha256 OR
            NEW.commit_request_sha256 IS NOT OLD.commit_request_sha256 OR
            NEW.remote_request_sha256 IS NOT OLD.remote_request_sha256 OR
            NEW.credential_reference_sha256 IS NOT OLD.credential_reference_sha256 OR
            NEW.created_at!=OLD.created_at
          THEN RAISE(ABORT, 'Git operation immutable facts changed') END;
          SELECT CASE WHEN
            NOT (
              NEW.aggregate_effect_knowledge=OLD.aggregate_effect_knowledge OR
              (OLD.aggregate_effect_knowledge='none' AND
               NEW.aggregate_effect_knowledge IN
               ('known_no_effect','known_effect','partial','uncertain')) OR
              (OLD.aggregate_effect_knowledge='uncertain' AND
               NEW.aggregate_effect_knowledge IN
               ('known_no_effect','known_effect','partial')) OR
              (OLD.aggregate_effect_knowledge='partial' AND
               NEW.aggregate_effect_knowledge='known_effect')
            ) OR NOT (
              NEW.state=OLD.state OR
              (OLD.state='planned' AND
               NEW.state IN ('active','recovery_required','terminal')) OR
              (OLD.state='active' AND NEW.state IN ('recovery_required','terminal')) OR
              (OLD.state='recovery_required' AND NEW.state='terminal')
            ) OR NEW.current_stage_generation<OLD.current_stage_generation OR
            NEW.updated_at<OLD.updated_at OR
            (OLD.last_reconciled_at IS NOT NULL AND
             (NEW.last_reconciled_at IS NULL OR
              NEW.last_reconciled_at<OLD.last_reconciled_at))
          THEN RAISE(ABORT, 'Git operation state regressed') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER git_operation_stages_guarded_update
        BEFORE UPDATE ON git_operation_stages
        BEGIN
          SELECT CASE WHEN
            NEW.operation_id!=OLD.operation_id OR
            NEW.stage_generation!=OLD.stage_generation OR NEW.member_id!=OLD.member_id OR
            NEW.stage_kind!=OLD.stage_kind OR NEW.input_sha256!=OLD.input_sha256 OR
            NEW.pre_state_sha256!=OLD.pre_state_sha256 OR
            NEW.member_ticket_id IS NOT OLD.member_ticket_id OR
            NEW.member_ticket_sha256 IS NOT OLD.member_ticket_sha256 OR
            NEW.before_oid_algorithm IS NOT OLD.before_oid_algorithm OR
            NEW.before_oid_hex IS NOT OLD.before_oid_hex OR
            NEW.created_at!=OLD.created_at
          THEN RAISE(ABORT, 'Git stage immutable facts changed') END;
          SELECT CASE WHEN
            (OLD.acceptance_state!='unresolved' AND
             NEW.acceptance_state!=OLD.acceptance_state) OR
            (OLD.execution_id IS NOT NULL AND NEW.execution_id IS NOT OLD.execution_id) OR
            (OLD.after_oid_algorithm IS NOT NULL AND
             NEW.after_oid_algorithm IS NOT OLD.after_oid_algorithm) OR
            (OLD.after_oid_hex IS NOT NULL AND NEW.after_oid_hex IS NOT OLD.after_oid_hex) OR
            (OLD.cleanup_evidence_sha256 IS NOT NULL AND
             NEW.cleanup_evidence_sha256 IS NOT OLD.cleanup_evidence_sha256) OR
            (OLD.closed_at IS NOT NULL AND NEW.closed_at IS NOT OLD.closed_at) OR
            NOT (
              NEW.crossing_state=OLD.crossing_state OR
              (OLD.crossing_state='not_crossed' AND
               NEW.crossing_state IN ('start_committed','classified')) OR
              (OLD.crossing_state='start_committed' AND NEW.crossing_state='classified')
            ) OR NOT (
              NEW.effect_knowledge=OLD.effect_knowledge OR
              (OLD.effect_knowledge='none' AND
               NEW.effect_knowledge IN ('known_no_effect','known_effect','partial','uncertain')) OR
              (OLD.effect_knowledge='uncertain' AND
               NEW.effect_knowledge IN ('known_no_effect','known_effect','partial')) OR
              (OLD.effect_knowledge='partial' AND NEW.effect_knowledge='known_effect')
            ) OR NOT (
              NEW.state=OLD.state OR
              (OLD.state='planned' AND NEW.state IN
               ('dispatched','running','cleanup_pending','closed','uncertain')) OR
              (OLD.state='dispatched' AND NEW.state IN
               ('running','cleanup_pending','closed','uncertain')) OR
              (OLD.state='running' AND NEW.state IN
               ('cleanup_pending','closed','uncertain')) OR
              (OLD.state='cleanup_pending' AND NEW.state IN ('closed','uncertain')) OR
              (OLD.state='uncertain' AND NEW.state='closed')
            ) OR NEW.cancel_generation<OLD.cancel_generation OR
            NEW.acknowledged_cancel_generation<OLD.acknowledged_cancel_generation OR
            NEW.executor_evidence_generation<OLD.executor_evidence_generation OR
            NEW.cleanup_complete<OLD.cleanup_complete OR NEW.updated_at<OLD.updated_at OR
            (OLD.state='closed' AND NEW.state!='closed')
          THEN RAISE(ABORT, 'Git stage evidence regressed') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER git_commit_evidence_guarded_update
        BEFORE UPDATE ON git_commit_evidence
        BEGIN
          SELECT CASE WHEN
            NEW.operation_id!=OLD.operation_id OR
            NEW.commit_oid_algorithm!=OLD.commit_oid_algorithm OR
            NEW.commit_oid_hex!=OLD.commit_oid_hex OR
            NEW.tree_oid_algorithm!=OLD.tree_oid_algorithm OR
            NEW.tree_oid_hex!=OLD.tree_oid_hex OR
            NEW.parent_oid_algorithm!=OLD.parent_oid_algorithm OR
            NEW.parent_oid_hex!=OLD.parent_oid_hex OR
            NEW.author_sha256!=OLD.author_sha256 OR
            NEW.committer_sha256!=OLD.committer_sha256 OR
            NEW.message_sha256!=OLD.message_sha256 OR
            NEW.preimage_sha256!=OLD.preimage_sha256 OR
            NEW.author_at!=OLD.author_at OR NEW.committer_at!=OLD.committer_at OR
            NEW.signer_profile_sha256!=OLD.signer_profile_sha256 OR
            NEW.signer_public_fingerprint!=OLD.signer_public_fingerprint OR
            NEW.signature_sha256!=OLD.signature_sha256 OR
            NEW.expected_main_index_identity_sha256!=
              OLD.expected_main_index_identity_sha256 OR
            NEW.expected_main_index_tree_oid_algorithm!=
              OLD.expected_main_index_tree_oid_algorithm OR
            NEW.expected_main_index_tree_oid_hex!=OLD.expected_main_index_tree_oid_hex OR
            NEW.expected_main_index_sha256!=OLD.expected_main_index_sha256 OR
            NEW.target_main_index_tree_oid_algorithm!=
              OLD.target_main_index_tree_oid_algorithm OR
            NEW.target_main_index_tree_oid_hex!=OLD.target_main_index_tree_oid_hex OR
            NEW.target_main_index_sha256!=OLD.target_main_index_sha256 OR
            NEW.selected_worktree_snapshot_sha256!=OLD.selected_worktree_snapshot_sha256 OR
            NEW.created_at!=OLD.created_at
          THEN RAISE(ABORT, 'Git commit immutable facts changed') END;
          SELECT CASE WHEN
            NEW.signature_verified<OLD.signature_verified OR
            NEW.object_imported<OLD.object_imported OR
            NEW.branch_cas_complete<OLD.branch_cas_complete OR
            (OLD.main_index_publication_receipt_sha256 IS NOT NULL AND
             NEW.main_index_publication_receipt_sha256 IS NOT
               OLD.main_index_publication_receipt_sha256) OR
            (OLD.worktree_evidence_sha256 IS NOT NULL AND
             NEW.worktree_evidence_sha256 IS NOT OLD.worktree_evidence_sha256) OR
            NOT (
              NEW.main_index_publication_state=OLD.main_index_publication_state OR
              (OLD.main_index_publication_state='pending' AND
               NEW.main_index_publication_state IN ('not_required','complete','uncertain')) OR
              (OLD.main_index_publication_state='uncertain' AND
               NEW.main_index_publication_state='complete')
            ) OR NEW.updated_at<OLD.updated_at
          THEN RAISE(ABORT, 'Git commit evidence regressed') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER git_remote_evidence_guarded_update
        BEFORE UPDATE ON git_remote_evidence
        BEGIN
          SELECT CASE WHEN
            NEW.operation_id!=OLD.operation_id OR
            NEW.remote_profile_sha256!=OLD.remote_profile_sha256 OR
            NEW.destination_sha256!=OLD.destination_sha256 OR
            NEW.outbound_closure_sha256!=OLD.outbound_closure_sha256 OR
            NEW.source_ref!=OLD.source_ref OR NEW.destination_ref!=OLD.destination_ref OR
            NEW.expected_remote_state!=OLD.expected_remote_state OR
            NEW.expected_oid_algorithm IS NOT OLD.expected_oid_algorithm OR
            NEW.expected_oid_hex IS NOT OLD.expected_oid_hex OR
            NEW.desired_oid_algorithm!=OLD.desired_oid_algorithm OR
            NEW.desired_oid_hex!=OLD.desired_oid_hex OR NEW.created_at!=OLD.created_at
          THEN RAISE(ABORT, 'Git remote immutable facts changed') END;
          SELECT CASE WHEN
            (OLD.observed_oid_algorithm IS NOT NULL AND
             NEW.observed_oid_algorithm IS NOT OLD.observed_oid_algorithm) OR
            (OLD.observed_oid_hex IS NOT NULL AND
             NEW.observed_oid_hex IS NOT OLD.observed_oid_hex) OR
            (OLD.credential_use_evidence_sha256 IS NOT NULL AND
             NEW.credential_use_evidence_sha256 IS NOT
               OLD.credential_use_evidence_sha256) OR
            NEW.remote_reconciled<OLD.remote_reconciled OR
            NEW.credential_cleanup_complete<OLD.credential_cleanup_complete OR
            NOT (
              NEW.transport_state=OLD.transport_state OR
              (OLD.transport_state='not_started' AND NEW.transport_state IN
               ('accepted','sent','lost_response','completed','uncertain')) OR
              (OLD.transport_state='accepted' AND NEW.transport_state IN
               ('sent','lost_response','completed','uncertain')) OR
              (OLD.transport_state='sent' AND NEW.transport_state IN
               ('lost_response','completed','uncertain')) OR
              (OLD.transport_state IN ('lost_response','uncertain') AND
               NEW.transport_state='completed')
            ) OR NEW.updated_at<OLD.updated_at
          THEN RAISE(ABORT, 'Git remote evidence regressed') END;
        END
        """
    )
    op.execute(
        "UPDATE kernel_meta SET schema_generation=5, updated_at=CURRENT_TIMESTAMP "
        "WHERE id=1 AND schema_generation=4"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE kernel_meta SET schema_generation=4, updated_at=CURRENT_TIMESTAMP "
        "WHERE id=1 AND schema_generation=5"
    )
    op.execute("DROP TRIGGER git_remote_evidence_guarded_update")
    op.execute("DROP TRIGGER git_commit_evidence_guarded_update")
    op.execute("DROP TRIGGER git_operation_stages_guarded_update")
    op.execute("DROP TRIGGER git_operations_guarded_update")
    for table in (
        "git_remote_evidence",
        "git_commit_evidence",
        "git_operation_stages",
        "git_operations",
    ):
        op.execute(f"DROP TRIGGER {table}_no_delete")
    op.drop_table("git_remote_evidence")
    op.drop_table("git_commit_evidence")
    op.drop_index("uq_git_stages_active_member", table_name="git_operation_stages")
    op.drop_table("git_operation_stages")
    op.drop_index("ix_git_operations_session", table_name="git_operations")
    op.drop_table("git_operations")


def _required_oid_shape(prefix: str) -> str:
    algorithm = f"{prefix}_oid_algorithm"
    hexadecimal = f"{prefix}_oid_hex"
    return (
        f"{algorithm} IN {_OID_ALGORITHMS} AND "
        f"length({hexadecimal})=CASE {algorithm} WHEN 'sha1' THEN 40 ELSE 64 END "
        f"AND {hexadecimal} NOT GLOB '*[^0-9a-f]*'"
    )


def _optional_oid_shape(prefix: str) -> str:
    algorithm = f"{prefix}_oid_algorithm"
    hexadecimal = f"{prefix}_oid_hex"
    return (
        f"(({algorithm} IS NULL AND {hexadecimal} IS NULL) OR "
        f"({algorithm} IS NOT NULL AND {hexadecimal} IS NOT NULL AND "
        f"{_required_oid_shape(prefix)}))"
    )
