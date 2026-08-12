from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

REVISION = "0001_privileged_evidence"
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def _config(repo_root: Path, database: Path) -> Config:
    config = Config(repo_root / "alembic_privileged.ini")
    config.set_main_option("script_location", str(repo_root / "migrations_privileged"))
    config.attributes["database_url"] = f"sqlite:///{database}"
    return config


def _migrate(repo_root: Path, database: Path) -> None:
    command.upgrade(_config(repo_root, database), "head")


def _insert_binding(
    connection: sqlite3.Connection,
    *,
    operation_id: str = "operation-1",
    ticket_id: str = "ticket-1",
    ticket_digest: str = DIGEST_A,
    nonce_digest: str = DIGEST_B,
) -> None:
    connection.execute(
        """
        INSERT INTO privileged_operation_bindings (
          operation_id,ticket_id,ticket_sha256,ticket_nonce_sha256,action,
          target_profile_id,target_profile_sha256,broker_profile_sha256,
          request_fingerprint_sha256,current_state_binding_sha256,
          policy_evidence_sha256,expires_at,acceptance_state,evidence_generation,
          acceptance_evidence_sha256,created_at,accepted_at,sealed_at,updated_at
        ) VALUES (?,?,?,?, 'package_install','development-packages',?,?,?,?,?,
                  datetime(CURRENT_TIMESTAMP,'+2 minutes'),'unresolved',0,NULL,
                  CURRENT_TIMESTAMP,NULL,NULL,CURRENT_TIMESTAMP)
        """,
        (
            operation_id,
            ticket_id,
            ticket_digest,
            nonce_digest,
            DIGEST_A,
            DIGEST_B,
            DIGEST_C,
            DIGEST_A,
            DIGEST_B,
        ),
    )


def test_privileged_migration_is_isolated_empty_and_reversible(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    database = tmp_path / "privileged.sqlite3"
    config = _config(repo_root, database)
    command.upgrade(config, "head")
    with closing(sqlite3.connect(database)) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
            if table not in {"alembic_version", "privileged_meta"}
        }
        meta = connection.execute(
            "SELECT schema_generation,readiness FROM privileged_meta WHERE id=1"
        ).fetchone()

    assert revision == (REVISION,)
    assert tables == {
        "alembic_version",
        "privileged_meta",
        "privileged_operation_bindings",
        "privileged_no_accept_tombstones",
        "privileged_subeffects",
        "privileged_evidence_events",
    }
    assert counts == {table: 0 for table in counts}
    assert meta == (1, "disabled")

    command.downgrade(config, "base")
    with closing(sqlite3.connect(database)) as connection:
        remaining = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    assert remaining == {"alembic_version"}


def test_one_operation_ticket_binding_is_immutable_and_globally_unique(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    database = tmp_path / "privileged.sqlite3"
    _migrate(repo_root, database)
    with closing(sqlite3.connect(database)) as connection, connection:
        _insert_binding(connection)
        with pytest.raises(sqlite3.IntegrityError, match="ticket binding changed"):
            connection.execute(
                "UPDATE privileged_operation_bindings SET ticket_id='replacement' "
                "WHERE operation_id='operation-1'"
            )
        for operation_id, ticket_id, ticket_digest, nonce_digest in (
            ("operation-2", "ticket-1", DIGEST_C, "d" * 64),
            ("operation-3", "ticket-3", DIGEST_A, "e" * 64),
            ("operation-4", "ticket-4", "f" * 64, DIGEST_B),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                _insert_binding(
                    connection,
                    operation_id=operation_id,
                    ticket_id=ticket_id,
                    ticket_digest=ticket_digest,
                    nonce_digest=nonce_digest,
                )
        with pytest.raises(sqlite3.IntegrityError, match="retained"):
            connection.execute(
                "DELETE FROM privileged_operation_bindings WHERE operation_id='operation-1'"
            )


def test_accept_or_seal_has_one_durable_winner(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    accepted_database = tmp_path / "accepted.sqlite3"
    _migrate(repo_root, accepted_database)
    with closing(sqlite3.connect(accepted_database)) as connection, connection:
        _insert_binding(connection)
        connection.execute(
            """
            UPDATE privileged_operation_bindings
            SET acceptance_state='accepted',evidence_generation=1,
                acceptance_evidence_sha256=?,accepted_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP
            WHERE operation_id='operation-1'
            """,
            (DIGEST_C,),
        )
        with pytest.raises(sqlite3.IntegrityError, match="conflicts with ticket binding"):
            connection.execute(
                """
                INSERT INTO privileged_no_accept_tombstones VALUES (
                  'operation-1','ticket-1',?,'replacement_recovery',?,2,?,
                  CURRENT_TIMESTAMP,datetime(CURRENT_TIMESTAMP,'+1 day'),CURRENT_TIMESTAMP
                )
                """,
                (DIGEST_A, DIGEST_B, DIGEST_C),
            )

    sealed_database = tmp_path / "sealed.sqlite3"
    _migrate(repo_root, sealed_database)
    with closing(sqlite3.connect(sealed_database)) as connection, connection:
        _insert_binding(connection)
        connection.execute(
            """
            INSERT INTO privileged_no_accept_tombstones VALUES (
              'operation-1','ticket-1',?,'replacement_recovery',?,1,?,
              CURRENT_TIMESTAMP,datetime(CURRENT_TIMESTAMP,'+1 day'),CURRENT_TIMESTAMP
            )
            """,
            (DIGEST_A, DIGEST_B, DIGEST_C),
        )
        connection.execute(
            """
            UPDATE privileged_operation_bindings
            SET acceptance_state='sealed_no_accept',evidence_generation=1,
                acceptance_evidence_sha256=?,sealed_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP
            WHERE operation_id='operation-1'
            """,
            (DIGEST_C,),
        )
        with pytest.raises(sqlite3.IntegrityError, match="seal already won"):
            connection.execute(
                """
                UPDATE privileged_operation_bindings
                SET acceptance_state='accepted',accepted_at=CURRENT_TIMESTAMP,sealed_at=NULL
                WHERE operation_id='operation-1'
                """
            )


def test_subeffect_state_and_receipts_are_monotonic(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    database = tmp_path / "privileged.sqlite3"
    _migrate(repo_root, database)
    with closing(sqlite3.connect(database)) as connection, connection:
        _insert_binding(connection)
        connection.execute(
            """
            UPDATE privileged_operation_bindings
            SET acceptance_state='accepted',evidence_generation=1,
                acceptance_evidence_sha256=?,accepted_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP
            WHERE operation_id='operation-1'
            """,
            (DIGEST_C,),
        )
        connection.execute(
            """
            INSERT INTO privileged_subeffects VALUES (
              'operation-1',1,'subeffect-1','package_transaction',?,'intent_recorded',
              'none',NULL,NULL,NULL,CURRENT_TIMESTAMP,NULL,NULL,CURRENT_TIMESTAMP
            )
            """,
            (DIGEST_A,),
        )
        connection.execute(
            """
            UPDATE privileged_subeffects
            SET state='started',effect_knowledge='known_effect',effect_reference='apt-tx-1',
                boundary_receipt_sha256=?,started_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP
            WHERE operation_id='operation-1' AND subeffect_generation=1
            """,
            (DIGEST_B,),
        )
        connection.execute(
            """
            UPDATE privileged_subeffects
            SET state='terminal',result_evidence_sha256=?,closed_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP
            WHERE operation_id='operation-1' AND subeffect_generation=1
            """,
            (DIGEST_C,),
        )
        with pytest.raises(sqlite3.IntegrityError, match="evidence regressed"):
            connection.execute(
                "UPDATE privileged_subeffects SET state='started',closed_at=NULL "
                "WHERE operation_id='operation-1' AND subeffect_generation=1"
            )
        with pytest.raises(sqlite3.IntegrityError, match="retained"):
            connection.execute("DELETE FROM privileged_subeffects")
