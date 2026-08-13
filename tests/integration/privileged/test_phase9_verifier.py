from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from scripts.verify_privileged_broker import (
    PrivilegedBrokerVerificationError,
    require_default_disabled,
    temporary_verification,
    verify_database,
)

from binnacle.privileged_broker import (
    PrivilegedBrokerIntegrityError,
    verify_privileged_broker_connection,
)


def test_temporary_privileged_verifier_is_exact_and_default_disabled(repo_root: Path) -> None:
    report = temporary_verification(repo_root)

    assert report.revision == "0001_privileged_evidence"
    assert report.schema_generation == 1
    assert report.readiness == "disabled"
    assert report.evidence_generation == 0
    assert report.package_plans == 0
    assert report.runtime_slots == 0
    assert report.restart_checkpoints == 0
    assert report.selector_generations == 0
    assert not report.retains_authority


def test_privileged_verifier_rejects_unsafe_database_path(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    database = tmp_path / "evidence.db"
    _migrate(database, repo_root)
    database.chmod(0o640)
    with pytest.raises(PrivilegedBrokerVerificationError, match="path is unsafe"):
        verify_database(database)

    database.chmod(0o600)
    wrong_name = tmp_path / "wrong.sqlite3"
    database.replace(wrong_name)
    with pytest.raises(PrivilegedBrokerVerificationError, match="path is unsafe"):
        verify_database(wrong_name)


def test_integrity_rejects_event_gaps_and_sealed_binding_without_tombstone(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    database = tmp_path / "evidence.db"
    _migrate(database, repo_root)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE privileged_meta SET evidence_generation_high_water=1 WHERE id=1")
        with pytest.raises(PrivilegedBrokerIntegrityError, match="generation has a gap"):
            verify_privileged_broker_connection(connection)

    sealed_root = tmp_path / "sealed"
    sealed_root.mkdir()
    sealed_database = sealed_root / "evidence.db"
    _migrate(sealed_database, repo_root)
    with closing(sqlite3.connect(sealed_database)) as connection, connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute(
            """
            INSERT INTO privileged_operation_bindings (
              operation_id,ticket_id,ticket_sha256,ticket_nonce_sha256,action,
              target_profile_id,target_profile_sha256,broker_profile_sha256,
              request_fingerprint_sha256,current_state_binding_sha256,
              policy_evidence_sha256,expires_at,acceptance_state,evidence_generation,
              acceptance_evidence_sha256,execution_state,active_slot,effect_knowledge,
              result_evidence_sha256,created_at,accepted_at,sealed_at,closed_at,
              updated_at,last_reconciled_at
            ) VALUES (
              'operation-1','ticket-1',?,?,?,'target',?,?,?,?,?,
              datetime(CURRENT_TIMESTAMP,'+2 minutes'),'sealed_no_accept',0,NULL,
              'terminal',NULL,'known_no_subeffect',NULL,CURRENT_TIMESTAMP,NULL,NULL,NULL,
              CURRENT_TIMESTAMP,NULL
            )
            """,
            (
                "a" * 64,
                "b" * 64,
                "package_install",
                "c" * 64,
                "d" * 64,
                "e" * 64,
                "f" * 64,
                "1" * 64,
            ),
        )
        with pytest.raises(PrivilegedBrokerIntegrityError, match="lacks tombstone"):
            verify_privileged_broker_connection(connection)


def test_default_disabled_gate_rejects_promoted_or_retained_authority(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    database = tmp_path / "evidence.db"
    _migrate(database, repo_root)
    database.chmod(0o600)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE privileged_meta SET readiness='ready' WHERE id=1")
    report = verify_database(database)
    with pytest.raises(PrivilegedBrokerVerificationError, match="promoted"):
        require_default_disabled(report)

    retained_root = tmp_path / "retained"
    retained_root.mkdir()
    retained_database = retained_root / "evidence.db"
    _migrate(retained_database, repo_root)
    retained_database.chmod(0o600)
    with closing(sqlite3.connect(retained_database)) as connection, connection:
        _insert_slot(connection, slot_id="lkg-slot", generation=1, state="lkg")
        connection.execute(
            """
            INSERT INTO privileged_selector_generations VALUES (
              1,NULL,1,NULL,'lkg-slot',?,'verified',?,?,CURRENT_TIMESTAMP,
              CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
            )
            """,
            ("a" * 64, "b" * 64, "c" * 64),
        )
    retained_report = verify_database(retained_database)
    assert retained_report.runtime_slots == 1
    assert retained_report.selector_generations == 1
    assert retained_report.retains_authority
    with pytest.raises(PrivilegedBrokerVerificationError, match="retains broker evidence"):
        require_default_disabled(retained_report)


def test_integrity_rejects_specialized_evidence_for_the_wrong_action(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    database = tmp_path / "evidence.db"
    _migrate(database, repo_root)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            """
            INSERT INTO privileged_operation_bindings (
              operation_id,ticket_id,ticket_sha256,ticket_nonce_sha256,action,
              target_profile_id,target_profile_sha256,broker_profile_sha256,
              request_fingerprint_sha256,current_state_binding_sha256,
              policy_evidence_sha256,expires_at,acceptance_state,evidence_generation,
              acceptance_evidence_sha256,execution_state,active_slot,effect_knowledge,
              result_evidence_sha256,created_at,accepted_at,sealed_at,closed_at,
              updated_at,last_reconciled_at
            ) VALUES (
              'operation-1','ticket-1',?,?,?,'target',?,?,?,?,?,
              datetime(CURRENT_TIMESTAMP,'+2 minutes'),'accepted',1,?,
              'accepted_pre_effect',1,'none',NULL,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,NULL,NULL,
              CURRENT_TIMESTAMP,NULL
            )
            """,
            (
                "a" * 64,
                "b" * 64,
                "package_install",
                "c" * 64,
                "d" * 64,
                "e" * 64,
                "f" * 64,
                "1" * 64,
                "2" * 64,
            ),
        )
        connection.execute(
            "INSERT INTO privileged_evidence_events VALUES "
            "(1,'event-1','operation-1','ticket.accepted',?,CURRENT_TIMESTAMP)",
            ("2" * 64,),
        )
        connection.execute("UPDATE privileged_meta SET evidence_generation_high_water=1 WHERE id=1")
        _insert_slot(connection, slot_id="lkg-slot", generation=1, state="lkg")
        _insert_slot(connection, slot_id="candidate-slot", generation=2, state="complete")
        connection.execute(
            """
            INSERT INTO privileged_restart_checkpoints (
              operation_id,service_profile_sha256,workspace_id,workspace_fence_version,
              evidence_generation,candidate_slot_id,lkg_slot_id,selected_slot_id,
              current_runtime_identity_sha256,current_service_observation_sha256,
              outstanding_state_sha256,preflight_state_binding_sha256,preflight_observed_at,
              candidate_verification_sha256,peer_set_sha256,schema_heads_sha256,
              restart_deadline_seconds,checkpoint_sha256,state,outcome,result_evidence_sha256,
              created_at,service_stopped_at,closed_at,updated_at
            ) VALUES (
              'operation-1',?,'workspace-1',1,1,'candidate-slot','lkg-slot',NULL,
              ?,?,?,?,CURRENT_TIMESTAMP,?,?,?,120,?,'prepared','pending',NULL,
              CURRENT_TIMESTAMP,NULL,NULL,CURRENT_TIMESTAMP
            )
            """,
            (
                "a" * 64,
                "b" * 64,
                "c" * 64,
                "d" * 64,
                "e" * 64,
                "4" * 64,
                "1" * 64,
                "2" * 64,
                "5" * 64,
            ),
        )
        with pytest.raises(
            PrivilegedBrokerIntegrityError,
            match="accepted complete slot evidence",
        ):
            verify_privileged_broker_connection(connection)


def _migrate(database: Path, repo_root: Path) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(repo_root / "alembic_privileged.ini")
    config.set_main_option("script_location", str(repo_root / "migrations_privileged"))
    config.attributes["database_url"] = f"sqlite:///{database}"
    command.upgrade(config, "head")


def _insert_slot(
    connection: sqlite3.Connection,
    *,
    slot_id: str,
    generation: int,
    state: str,
) -> None:
    role = {
        "complete": "candidate",
        "lkg": "lkg",
        "prior": "prior",
    }[state]
    connection.execute(
        """
        INSERT INTO privileged_runtime_slots VALUES (
          ?,?,?,?, ?, ?,?,?,?,?, ?,?,?,?,?, ?,4096,64,CURRENT_TIMESTAMP,
          CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
        )
        """,
        (
            slot_id,
            generation,
            f"/srv/binnacle-runtime/slots/{slot_id}",
            role,
            state,
            "a" * 64,
            "b" * 64,
            "c" * 64,
            "d" * 64,
            "e" * 64,
            "f" * 64,
            "1" * 64,
            "2" * 64,
            "3" * 64,
            "4" * 64,
            "5" * 64,
        ),
    )
