#!/usr/bin/env python3
"""Read-only privileged-broker verification, with an isolated temporary CI lane."""

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

from binnacle.privileged_broker import (
    PrivilegedBrokerIntegrityError,
    PrivilegedBrokerIntegrityReport,
    verify_privileged_broker_connection,
)


class PrivilegedBrokerVerificationError(RuntimeError):
    """The root-broker evidence store cannot be safely verified."""


def verify_database(path: Path) -> PrivilegedBrokerIntegrityReport:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise PrivilegedBrokerVerificationError("privileged database is unavailable") from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or path.name != "evidence.db"
        or metadata.st_uid != os.geteuid()
        or metadata.st_gid != os.getegid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise PrivilegedBrokerVerificationError("privileged database path is unsafe")
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        try:
            connection.execute("PRAGMA query_only=ON")
            return verify_privileged_broker_connection(connection)
        finally:
            connection.close()
    except (PrivilegedBrokerIntegrityError, sqlite3.Error) as exc:
        raise PrivilegedBrokerVerificationError("privileged database verification failed") from exc


def require_default_disabled(report: PrivilegedBrokerIntegrityReport) -> None:
    if (
        report.readiness not in {"uninitialized", "disabled"}
        or report.retains_authority
        or report.accepted_bindings
        or report.sealed_bindings
    ):
        raise PrivilegedBrokerVerificationError(
            "privileged capability is promoted or retains broker evidence"
        )


def temporary_verification(repo_root: Path) -> PrivilegedBrokerIntegrityReport:
    with tempfile.TemporaryDirectory(prefix="binnacle-privileged-verify-") as temporary:
        database = Path(temporary) / "evidence.db"
        config = Config(repo_root / "alembic_privileged.ini")
        config.set_main_option("script_location", str(repo_root / "migrations_privileged"))
        config.attributes["database_url"] = f"sqlite:///{database}"
        command.upgrade(config, "head")
        database.chmod(0o600)
        report = verify_database(database)
        require_default_disabled(report)
        return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--temporary", action="store_true")
    source.add_argument("--database", type=Path)
    parser.add_argument("--require-default-disabled", action="store_true")
    parser.add_argument("--output", choices=("human", "json"), default="human")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        report = (
            temporary_verification(Path(__file__).resolve().parents[1])
            if arguments.temporary
            else verify_database(arguments.database)
        )
        if arguments.require_default_disabled:
            require_default_disabled(report)
    except (PrivilegedBrokerVerificationError, OSError, sqlite3.Error) as exc:
        print(f"Privileged-broker verification failed: {type(exc).__name__}")
        return 1
    if arguments.output == "json":
        print(json.dumps(asdict(report), sort_keys=True, separators=(",", ":")))
    else:
        print(
            f"privileged revision={report.revision} readiness={report.readiness} "
            f"evidence_generation={report.evidence_generation}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
