#!/usr/bin/env python3
"""Read-only credential-broker verification, with an isolated temporary CI lane."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import stat
import tempfile
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote

from alembic import command
from alembic.config import Config

from binnacle.credential_broker import (
    CredentialBrokerIntegrityError,
    CredentialBrokerIntegrityReport,
    verify_credential_broker_connection,
)


class GitCredentialBrokerVerificationError(RuntimeError):
    """The isolated credential-broker store cannot be safely verified."""


def verify_database(path: Path) -> CredentialBrokerIntegrityReport:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise GitCredentialBrokerVerificationError("credential database is unavailable") from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or path.name != "git-credential-evidence.sqlite3"
        or metadata.st_uid != os.geteuid()
        or metadata.st_gid != os.getegid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise GitCredentialBrokerVerificationError("credential database path is unsafe")
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        try:
            connection.execute("PRAGMA query_only=ON")
            report = verify_credential_broker_connection(connection)
        finally:
            connection.close()
    except (CredentialBrokerIntegrityError, sqlite3.Error) as exc:
        raise GitCredentialBrokerVerificationError(
            "credential database verification failed"
        ) from exc
    if report.readiness not in {"uninitialized", "disabled"} or any(
        (
            report.registered_tickets,
            report.accepted_tickets,
            report.completed_tickets,
            report.uncertain_tickets,
        )
    ):
        raise GitCredentialBrokerVerificationError(
            "credential capability is promoted or retains unresolved authority"
        )
    return report


def verify_paths(database: Path, runtime_directory: Path) -> None:
    for path in (database.parent, runtime_directory):
        try:
            metadata = path.stat(follow_symlinks=False)
        except OSError as exc:
            raise GitCredentialBrokerVerificationError(
                "credential private directory is unavailable"
            ) from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise GitCredentialBrokerVerificationError(
                "credential private directory ownership is unsafe"
            )


def temporary_verification(repo_root: Path) -> CredentialBrokerIntegrityReport:
    with tempfile.TemporaryDirectory(prefix="binnacle-git-credential-verify-") as temporary:
        state = Path(temporary) / "state"
        state.mkdir(mode=0o700)
        database = state / "git-credential-evidence.sqlite3"
        config = Config(repo_root / "alembic-git-credential.ini")
        config.set_main_option("script_location", str(repo_root / "migrations_git_credential"))
        config.attributes["database_url"] = f"sqlite:///{database}"
        command.upgrade(config, "head")
        database.chmod(0o600)
        return verify_database(database)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--temporary", action="store_true")
    source.add_argument("--database", type=Path)
    parser.add_argument(
        "--runtime-directory",
        type=Path,
        default=Path("/run/binnacle-git-credential/private"),
    )
    parser.add_argument("--output", choices=("human", "json"), default="human")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.temporary:
            report = temporary_verification(Path(__file__).resolve().parents[1])
        else:
            assert arguments.database is not None
            verify_paths(arguments.database, arguments.runtime_directory)
            report = verify_database(arguments.database)
    except (GitCredentialBrokerVerificationError, OSError, sqlite3.Error) as exc:
        print(f"Git credential-broker verification failed: {type(exc).__name__}")
        return 1
    if arguments.output == "json":
        print(json.dumps(asdict(report), sort_keys=True, separators=(",", ":")))
    else:
        print(
            f"credential revision={report.revision} readiness={report.readiness} "
            f"evidence_generation={report.evidence_generation}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
