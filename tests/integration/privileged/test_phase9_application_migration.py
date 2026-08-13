"""Phase 9 application-side preparation, ticket, and reservation persistence."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from tests.phase4_support import migrate_database

from binnacle.adapters.verification import (
    KernelVerificationError,
    _verify_privileged_invariants,
)

NOW = "2026-08-13 00:00:00"
LATER = "2026-08-13 01:00:00"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _config(database: Path, repo_root: Path) -> Config:
    config = Config(repo_root / "alembic.ini")
    config.set_main_option("script_location", str(repo_root / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    return config


def _insert_owner(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO controller_owners (
          controller_id,controller_epoch,controller_profile_id,
          controller_profile_version,first_seen_at,last_seen_at,active
        ) VALUES ('controller-phase9',1,'controller-profile','1',?,?,1)
        """,
        (NOW, NOW),
    )


def _insert_operation(
    connection: sqlite3.Connection,
    *,
    operation_id: str,
    contract: str,
    state: str,
    effect_knowledge: str,
    terminality: str,
) -> None:
    _insert_owner(connection)
    connection.execute(
        """
        INSERT INTO operations (
          operation_id,controller_id,controller_epoch,device_id,device_epoch,
          operation_contract,operation_contract_version,tool_name,tool_contract_version,
          request_fingerprint_sha256,state,state_version,effect_knowledge,terminality,
          automatic_retry_allowed,effect_boundary_crossed_at,effect_reference,
          effect_reference_digest,error_code,error_summary,retry_action,
          runtime_build_sha256,runtime_config_sha256,
          controller_profile_version_snapshot,created_at,updated_at,authorised_at,
          started_at,terminal_at,last_reconciled_at
        ) VALUES (
          ?,'controller-phase9',1,'device-phase9',1,?,'1',?,'1',?, ?,1,?,?,0,
          NULL,NULL,NULL,NULL,NULL,NULL,?,?,?, ?,?,?,?, ?,NULL
        )
        """,
        (
            operation_id,
            contract,
            contract,
            _digest(f"request:{operation_id}"),
            state,
            effect_knowledge,
            terminality,
            _digest("runtime-build"),
            _digest("runtime-config"),
            _digest("controller-profile"),
            NOW,
            NOW,
            NOW,
            NOW if terminality == "terminal" else None,
            NOW if terminality == "terminal" else None,
        ),
    )


def _insert_policy(
    connection: sqlite3.Connection,
    *,
    operation_id: str,
    contract: str,
    target_sha256: str,
    policy_sha256: str,
) -> str:
    policy_id = f"policy-{operation_id}"
    connection.execute(
        """
        INSERT INTO policy_decisions (
          policy_decision_id,operation_id,policy_id,policy_version,decision,
          controller_id,controller_epoch,operation_contract,operation_contract_version,
          required_scope_digest,normalized_target_digest,input_facts_sha256,
          reason_codes_json,decided_at,runtime_policy_sha256
        ) VALUES (?,?, 'phase9-policy','1','allow','controller-phase9',1,?,'1',
                  NULL,?,?, '[]',?,?)
        """,
        (
            policy_id,
            operation_id,
            contract,
            target_sha256,
            _digest(f"facts:{operation_id}"),
            NOW,
            policy_sha256,
        ),
    )
    return policy_id


def _seed_package_operation(
    connection: sqlite3.Connection,
    *,
    suffix: str,
    reservation_generation: int,
    policy_override_sha256: str | None = None,
    add_reservation: bool = True,
) -> str:
    prepare_operation_id = f"prepare-{suffix}"
    operation_id = f"package-{suffix}"
    target_sha256 = _digest(f"target:{suffix}")
    policy_sha256 = _digest(f"policy:{suffix}")
    nonce_sha256 = _digest(f"nonce:{suffix}")
    prepared_sha256 = _digest(f"prepared:{suffix}")
    state_sha256 = _digest(f"state:{suffix}")
    plan_sha256 = _digest(f"plan:{suffix}")

    _insert_operation(
        connection,
        operation_id=prepare_operation_id,
        contract="privileged_prepare",
        state="succeeded",
        effect_knowledge="known_effect",
        terminality="terminal",
    )
    _insert_policy(
        connection,
        operation_id=prepare_operation_id,
        contract="privileged_prepare",
        target_sha256=target_sha256,
        policy_sha256=_digest(f"prepare-policy:{suffix}"),
    )
    connection.execute(
        """
        INSERT INTO privileged_preparations (
          prepare_operation_id,session_id,workspace_id,action,target_profile_id,
          target_profile_sha256,maximum_effect,normalized_request_sha256,
          current_state_binding_sha256,prepared_evidence_sha256,execution_nonce_sha256,
          package_transaction_plan_sha256,service_profile_sha256,
          candidate_verification_reference,candidate_verification_sha256,candidate_slot_id,
          lkg_slot_id,schema_heads_sha256,runtime_layout_sha256,deployed_peer_set_sha256,
          state,consumed_by_operation_id,created_at,expires_at,consumed_at,updated_at
        ) VALUES (
          ?,NULL,NULL,'package_install','package-profile',?,'package_change',?,?,?, ?,?,
          NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'available',NULL,?,?,NULL,?
        )
        """,
        (
            prepare_operation_id,
            target_sha256,
            _digest(f"normalized:{suffix}"),
            state_sha256,
            prepared_sha256,
            nonce_sha256,
            plan_sha256,
            NOW,
            LATER,
            NOW,
        ),
    )

    _insert_operation(
        connection,
        operation_id=operation_id,
        contract="package_install",
        state="authorised",
        effect_knowledge="none",
        terminality="non_terminal",
    )
    policy_id = _insert_policy(
        connection,
        operation_id=operation_id,
        contract="package_install",
        target_sha256=target_sha256,
        policy_sha256=policy_sha256,
    )
    connection.execute(
        """
        INSERT INTO privileged_operations (
          operation_id,prepare_operation_id,session_id,workspace_id,workspace_fence_version,
          reservation_generation,action,maximum_effect,target_profile_id,
          target_profile_sha256,broker_profile_id,broker_profile_sha256,
          prepared_evidence_sha256,current_state_binding_sha256,policy_decision_id,
          policy_evidence_sha256,ticket_id,ticket_sha256,ticket_nonce_sha256,
          ticket_issued_at,ticket_expires_at,
          broker_acceptance_state,broker_evidence_generation,
          broker_acceptance_evidence_sha256,package_transaction_plan_sha256,
          service_profile_sha256,candidate_verification_reference,
          candidate_verification_sha256,candidate_slot_id,lkg_slot_id,
          restart_checkpoint_sha256,schema_heads_sha256,runtime_layout_sha256,
          deployed_peer_set_sha256,candidate_outcome,rollback_outcome,
          broker_closure_state,broker_closure_evidence_sha256,audit_closure_state,
          audit_closure_evidence_sha256,fence_closure_state,fence_release_evidence_sha256,
          state,created_at,broker_decided_at,closed_at,updated_at,last_reconciled_at
        ) VALUES (
          ?,?,NULL,NULL,NULL,?,'package_install','package_change','package-profile',?,
          'broker-profile',?,?,?, ?,? ,?,?,?, ?,?,'unresolved',0,NULL,?,NULL,NULL,NULL,NULL,NULL,
          NULL,NULL,NULL,NULL,'not_applicable','not_applicable','pending',NULL,'pending',NULL,
          'not_applicable',NULL,'prepared',?,NULL,NULL,?,NULL
        )
        """,
        (
            operation_id,
            prepare_operation_id,
            reservation_generation,
            target_sha256,
            _digest("broker-profile"),
            prepared_sha256,
            state_sha256,
            policy_id,
            policy_override_sha256 or policy_sha256,
            f"ticket-{suffix}",
            _digest(f"ticket:{suffix}"),
            nonce_sha256,
            NOW,
            LATER,
            plan_sha256,
            NOW,
            NOW,
        ),
    )
    connection.execute(
        """
        UPDATE privileged_preparations
        SET state='consumed',consumed_by_operation_id=?,consumed_at=?,updated_at=?
        WHERE prepare_operation_id=?
        """,
        (operation_id, NOW, NOW, prepare_operation_id),
    )
    if add_reservation:
        connection.execute(
            """
            INSERT INTO privileged_effect_reservations (
              operation_id,workspace_id,workspace_fence_version,reservation_generation,
              active_slot,state,closure_evidence_sha256,acquired_at,released_at,updated_at
            ) VALUES (?,NULL,NULL,?,1,'held',NULL,?,NULL,?)
            """,
            (operation_id, reservation_generation, NOW, NOW),
        )
    return operation_id


def test_application_privileged_migration_is_exact_empty_and_reversible(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    database = tmp_path / "application.sqlite3"
    config = _config(database, repo_root)

    command.upgrade(config, "0005_git_operations")
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0005_git_operations",
        )
        assert not {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'privileged_%'"
            )
        }

    command.upgrade(config, "head")
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0006_privileged_operations",
        )
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'privileged_%'"
            )
        }
        assert tables == {
            "privileged_preparations",
            "privileged_operations",
            "privileged_effect_reservations",
        }
        assert all(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (0,)
            for table in tables
        )

    command.downgrade(config, "0005_git_operations")
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0005_git_operations",
        )
        assert not {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'privileged_%'"
            )
        }


def test_exact_policy_preparation_consumption_and_global_reservation(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    database = tmp_path / "application.sqlite3"
    migrate_database(database, repo_root)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError, match="exact policy authority"):
            _seed_package_operation(
                connection,
                suffix="wrong-policy",
                reservation_generation=1,
                policy_override_sha256=_digest("wrong-policy"),
            )
        connection.rollback()

        first = _seed_package_operation(
            connection,
            suffix="first",
            reservation_generation=1,
        )
        _verify_privileged_invariants(connection)
        connection.execute("SAVEPOINT competing_reservation")
        second = _seed_package_operation(
            connection,
            suffix="second",
            reservation_generation=2,
            add_reservation=False,
        )
        with pytest.raises(sqlite3.IntegrityError, match="active_slot"):
            connection.execute(
                """
                INSERT INTO privileged_effect_reservations VALUES (
                  ?,NULL,NULL,2,1,'held',NULL,?,NULL,?
                )
                """,
                (second, NOW, NOW),
            )
        connection.execute("ROLLBACK TO competing_reservation")
        connection.execute("RELEASE competing_reservation")

        connection.execute(
            """
            UPDATE privileged_effect_reservations
            SET active_slot=NULL,state='released',closure_evidence_sha256=?,
                released_at=?,updated_at=? WHERE operation_id=?
            """,
            (_digest("first-closure"), NOW, NOW, first),
        )
        with pytest.raises(KernelVerificationError, match="reservation closure"):
            _verify_privileged_invariants(connection)
        connection.execute(
            """
            UPDATE privileged_operations
            SET broker_acceptance_state='sealed_no_accept',broker_evidence_generation=1,
                broker_acceptance_evidence_sha256=?,broker_decided_at=?,
                broker_closure_state='complete',broker_closure_evidence_sha256=?,
                audit_closure_state='complete',audit_closure_evidence_sha256=?,
                state='terminal',closed_at=?,updated_at=?
            WHERE operation_id=?
            """,
            (
                _digest("first-no-accept"),
                NOW,
                _digest("first-broker-closure"),
                _digest("first-audit-closure"),
                NOW,
                NOW,
                first,
            ),
        )
        connection.execute(
            """
            UPDATE operations
            SET state='failed',effect_knowledge='known_no_effect',terminality='terminal',
                terminal_at=?,updated_at=? WHERE operation_id=?
            """,
            (NOW, NOW, first),
        )
        second = _seed_package_operation(
            connection,
            suffix="second",
            reservation_generation=2,
            add_reservation=False,
        )
        connection.execute(
            """
            INSERT INTO privileged_effect_reservations VALUES (
              ?,NULL,NULL,2,1,'held',NULL,?,NULL,?
            )
            """,
            (second, NOW, NOW),
        )
        _verify_privileged_invariants(connection)

        with pytest.raises(sqlite3.IntegrityError, match="retained"):
            connection.execute(
                "DELETE FROM privileged_operations WHERE operation_id=?",
                (first,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="state regressed"):
            connection.execute(
                """
                UPDATE privileged_preparations
                SET consumed_by_operation_id='alternate-operation',updated_at=?
                WHERE consumed_by_operation_id=?
                """,
                (NOW, second),
            )


def test_uncertain_privileged_effect_retains_the_global_reservation(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    database = tmp_path / "application.sqlite3"
    migrate_database(database, repo_root)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("PRAGMA foreign_keys=ON")
        operation_id = _seed_package_operation(
            connection,
            suffix="uncertain",
            reservation_generation=1,
        )
        connection.execute(
            """
            UPDATE privileged_effect_reservations
            SET state='uncertain',updated_at=? WHERE operation_id=?
            """,
            (NOW, operation_id),
        )
        connection.execute(
            """
            UPDATE privileged_operations
            SET broker_acceptance_state='accepted',broker_evidence_generation=1,
                broker_acceptance_evidence_sha256=?,broker_decided_at=?,
                broker_closure_state='uncertain',broker_closure_evidence_sha256=?,
                state='uncertain',updated_at=?
            WHERE operation_id=?
            """,
            (_digest("accepted"), NOW, _digest("uncertain"), NOW, operation_id),
        )
        connection.execute(
            "UPDATE operations SET state='uncertain',effect_knowledge='uncertain',"
            "updated_at=? WHERE operation_id=?",
            (NOW, operation_id),
        )
        _verify_privileged_invariants(connection)

        with pytest.raises(sqlite3.IntegrityError, match="active_slot"):
            second = _seed_package_operation(
                connection,
                suffix="blocked",
                reservation_generation=2,
            )
            raise AssertionError(second)
