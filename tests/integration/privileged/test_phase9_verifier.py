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
    assert not report.retains_authority


def test_privileged_verifier_rejects_unsafe_database_path(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    database = tmp_path / "privileged-evidence.sqlite3"
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
    database = tmp_path / "privileged-evidence.sqlite3"
    _migrate(database, repo_root)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE privileged_meta SET evidence_generation_high_water=1 WHERE id=1")
        with pytest.raises(PrivilegedBrokerIntegrityError, match="generation has a gap"):
            verify_privileged_broker_connection(connection)

    sealed_database = tmp_path / "sealed-privileged-evidence.sqlite3"
    _migrate(sealed_database, repo_root)
    with closing(sqlite3.connect(sealed_database)) as connection, connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute(
            """
            INSERT INTO privileged_operation_bindings VALUES (
              'operation-1','ticket-1',?,?,?,?, 'target',?,?,?,?,
              datetime(CURRENT_TIMESTAMP,'+2 minutes'),'sealed_no_accept',0,NULL,
              CURRENT_TIMESTAMP,NULL,NULL,CURRENT_TIMESTAMP
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
    database = tmp_path / "privileged-evidence.sqlite3"
    _migrate(database, repo_root)
    database.chmod(0o600)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE privileged_meta SET readiness='ready' WHERE id=1")
    report = verify_database(database)
    with pytest.raises(PrivilegedBrokerVerificationError, match="promoted"):
        require_default_disabled(report)


def _migrate(database: Path, repo_root: Path) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(repo_root / "alembic_privileged.ini")
    config.set_main_option("script_location", str(repo_root / "migrations_privileged"))
    config.attributes["database_url"] = f"sqlite:///{database}"
    command.upgrade(config, "head")
