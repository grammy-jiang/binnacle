from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from tests.phase4_support import migrate_database

from binnacle.credential_broker import (
    CREDENTIAL_BROKER_REVISION,
    CredentialBrokerIntegrityError,
    verify_credential_broker_connection,
)
from binnacle.executor.integrity import ExecutorIntegrityError, verify_executor_connection
from binnacle.executor.state import EXECUTOR_REVISION


def test_application_git_migration_is_exact_retained_and_default_empty(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    database = tmp_path / "application.sqlite3"
    migrate_database(database, repo_root)
    with closing(sqlite3.connect(database)) as connection, connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        generation = connection.execute(
            "SELECT schema_generation FROM kernel_meta WHERE id=1"
        ).fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'git_%'"
            )
        }
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        }

    assert revision == ("0005_git_operations",)
    assert generation is None
    assert tables == {
        "git_operations",
        "git_operation_stages",
        "git_commit_evidence",
        "git_remote_evidence",
    }
    assert counts == {table: 0 for table in tables}


def test_git_operation_constraints_bind_full_typed_oids_and_retained_identity(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    database = tmp_path / "application.sqlite3"
    migrate_database(database, repo_root)
    values = (
        "git-operation-fixture",
        "session-fixture",
        "workspace-fixture",
        "branch_create",
        "repository-v1",
        "a" * 64,
        "b" * 64,
        "c" * 64,
        1,
        "refs/heads/master",
        "refs/heads/agent/phase-08",
        "sha1",
        "1" * 40,
        "sha1",
        "2" * 40,
        "d" * 64,
        0,
        "none",
        "planned",
    )
    insert = """
        INSERT INTO git_operations (
          operation_id,session_id,workspace_id,operation_kind,repository_profile_id,
          repository_profile_sha256,repository_safety_sha256,
          repository_state_binding_sha256,workspace_fence_version,source_ref,destination_ref,
          expected_old_oid_algorithm,expected_old_oid_hex,desired_oid_algorithm,desired_oid_hex,
          request_sha256,current_stage_generation,aggregate_effect_knowledge,state,
          created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
    """
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(insert, values)
        with pytest.raises(sqlite3.IntegrityError, match="retained"):
            connection.execute("DELETE FROM git_operations")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE git_operations SET request_sha256=? WHERE operation_id=?",
                ("e" * 64, values[0]),
            )

    malformed = list(values)
    malformed[12] = "1" * 39
    malformed[0] = "malformed-oid"
    with closing(sqlite3.connect(database)) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(insert, tuple(malformed))


def test_executor_git_migration_is_separate_and_unpromoted_rows_fail_integrity(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    database = tmp_path / "executor.sqlite3"
    _migrate(database, repo_root / "alembic-executor.ini", repo_root / "migrations_executor")
    with closing(sqlite3.connect(database)) as connection, connection:
        report = verify_executor_connection(connection, expected_revision=EXECUTOR_REVISION)
        assert report.schema_generation == 2
        assert report.revision == "0002_git_members"
        connection.execute(
            """
            INSERT INTO git_read_generations (
              application_generation,application_instance_sha256,state,accepted_high_water,
              sealed_high_water,outstanding_domains,quiescence_receipt_sha256,opened_at,
              close_requested_at,drained_at
            ) VALUES (1,?,'open',0,0,0,NULL,CURRENT_TIMESTAMP,NULL,NULL)
            """,
            ("a" * 64,),
        )
        with pytest.raises(ExecutorIntegrityError, match="unpromoted Git"):
            verify_executor_connection(connection, expected_revision=EXECUTOR_REVISION)

    app_tables = {"operations", "git_operations", "command_operations"}
    with closing(sqlite3.connect(database)) as connection:
        executor_tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert not app_tables & executor_tables


def test_credential_broker_migration_is_isolated_and_default_disabled(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    database = tmp_path / "git-credential-evidence.sqlite3"
    _migrate(
        database,
        repo_root / "alembic-git-credential.ini",
        repo_root / "migrations_git_credential",
    )
    database.chmod(0o600)
    with closing(sqlite3.connect(database)) as connection, connection:
        report = verify_credential_broker_connection(connection)
        assert report.revision == CREDENTIAL_BROKER_REVISION
        assert report.readiness == "disabled"
        assert report.evidence_generation == 0
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert tables == {
        "alembic_version",
        "credential_meta",
        "credential_use_tickets",
        "credential_evidence_events",
    }
    assert not {"operations", "execution_records", "git_operations"} & tables


def test_credential_integrity_rejects_revision_tables_generation_and_retained_digest_drift(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    database = tmp_path / "git-credential-evidence.sqlite3"
    _migrate(
        database,
        repo_root / "alembic-git-credential.ini",
        repo_root / "migrations_git_credential",
    )
    with closing(sqlite3.connect(database)) as connection, connection:
        with pytest.raises(CredentialBrokerIntegrityError, match="identity"):
            verify_credential_broker_connection(connection, expected_revision="wrong")

        connection.execute("CREATE TABLE unexpected (id INTEGER)")
        with pytest.raises(CredentialBrokerIntegrityError, match="table set"):
            verify_credential_broker_connection(connection)
        connection.execute("DROP TABLE unexpected")

        connection.execute("UPDATE credential_meta SET evidence_generation_high_water=1")
        with pytest.raises(CredentialBrokerIntegrityError, match="generation has a gap"):
            verify_credential_broker_connection(connection)


def test_credential_schema_retains_event_ticket_and_metadata_history(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    database = tmp_path / "git-credential-evidence.sqlite3"
    _migrate(
        database,
        repo_root / "alembic-git-credential.ini",
        repo_root / "migrations_git_credential",
    )
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            """
            INSERT INTO credential_use_tickets (
              ticket_id,ticket_sha256,operation_id,member_id,action,audience_sha256,
              credential_reference_sha256,credential_generation,preimage_sha256,
              destination_sha256,expires_at,consume_generation,state,retained_response,
              retained_response_bytes,retained_response_sha256,evidence_sha256,
              cleanup_complete,registered_at,accepted_at,completed_at,updated_at
            ) VALUES (
              'ticket-1',?,'operation-1','member-1','commit_sign',?,?,1,?,NULL,
              datetime('now','+1 day'),1,'accepted',NULL,0,NULL,NULL,0,
              CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,NULL,CURRENT_TIMESTAMP
            )
            """,
            ("a" * 64, "b" * 64, "c" * 64, "d" * 64),
        )
        connection.execute(
            """
            INSERT INTO credential_evidence_events (
              evidence_generation,event_id,ticket_id,event_type,event_sha256,recorded_at
            ) VALUES (1,'event-1','ticket-1','ticket.accepted',?,CURRENT_TIMESTAMP)
            """,
            ("e" * 64,),
        )
        connection.execute(
            "UPDATE credential_meta SET evidence_generation_high_water=1, "
            "updated_at=datetime(updated_at,'+1 second') WHERE id=1"
        )

        with pytest.raises(sqlite3.IntegrityError, match="event evidence is immutable"):
            connection.execute(
                "UPDATE credential_evidence_events SET event_sha256=? WHERE event_id='event-1'",
                ("f" * 64,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="evidence regressed"):
            connection.execute(
                "UPDATE credential_use_tickets SET state='registered' WHERE ticket_id='ticket-1'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="metadata regressed"):
            connection.execute("UPDATE credential_meta SET broker_instance_id='changed' WHERE id=1")

        report = verify_credential_broker_connection(connection)
        assert report.evidence_generation == 1
        assert report.accepted_tickets == 1


def test_bare_credential_migration_requires_an_absolute_explicit_database(
    repo_root: Path,
) -> None:
    with pytest.raises(RuntimeError, match="absolute SQLite"):
        command.upgrade(Config(repo_root / "alembic-git-credential.ini"), "head")


def test_all_three_phase8_migrations_have_isolated_reversible_heads(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    application = tmp_path / "application.sqlite3"
    application_config = Config(repo_root / "alembic.ini")
    application_config.set_main_option("script_location", str(repo_root / "migrations"))
    application_config.set_main_option("sqlalchemy.url", f"sqlite:///{application}")
    command.upgrade(application_config, "head")
    command.downgrade(application_config, "0004_execution_operations")
    with closing(sqlite3.connect(application)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0004_execution_operations",
        )

    executor = tmp_path / "executor.sqlite3"
    executor_config = Config(repo_root / "alembic-executor.ini")
    executor_config.set_main_option("script_location", str(repo_root / "migrations_executor"))
    executor_config.attributes["database_url"] = f"sqlite:///{executor}"
    command.upgrade(executor_config, "head")
    command.downgrade(executor_config, "0001_executor_evidence")
    with closing(sqlite3.connect(executor)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0001_executor_evidence",
        )
        assert connection.execute(
            "SELECT schema_generation FROM executor_meta WHERE id=1"
        ).fetchone() == (1,)

    credential = tmp_path / "credential.sqlite3"
    credential_config = Config(repo_root / "alembic-git-credential.ini")
    credential_config.set_main_option(
        "script_location", str(repo_root / "migrations_git_credential")
    )
    credential_config.attributes["database_url"] = f"sqlite:///{credential}"
    command.upgrade(credential_config, "head")
    command.downgrade(credential_config, "base")
    with closing(sqlite3.connect(credential)) as connection:
        assert {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'credential_%'"
            )
        } == set()


def _migrate(database: Path, ini: Path, scripts: Path) -> None:
    config = Config(ini)
    config.set_main_option("script_location", str(scripts))
    config.attributes["database_url"] = f"sqlite:///{database}"
    command.upgrade(config, "head")
