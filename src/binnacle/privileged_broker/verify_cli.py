"""Read-only verification entrypoint shipped in the immutable broker runtime."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import stat
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote

from binnacle.privileged_broker.integrity import (
    PrivilegedBrokerIntegrityError,
    PrivilegedBrokerIntegrityReport,
    verify_privileged_broker_connection,
)

_DATABASE_PATH = Path("/var/lib/binnacle-privileged/evidence.db")


class InstalledPrivilegedVerificationError(RuntimeError):
    """The installed broker evidence cannot be verified without mutation."""


def verify_installed_database(path: Path = _DATABASE_PATH) -> PrivilegedBrokerIntegrityReport:
    if os.geteuid() != 0 or os.getegid() != 0:
        raise InstalledPrivilegedVerificationError("installed verification requires root")
    if path != _DATABASE_PATH:
        raise InstalledPrivilegedVerificationError("privileged database path is not protected")
    try:
        parent = path.parent.lstat()
        database = path.lstat()
    except OSError as exc:
        raise InstalledPrivilegedVerificationError("privileged database is unavailable") from exc
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_ISLNK(parent.st_mode)
        or (parent.st_uid, parent.st_gid, stat.S_IMODE(parent.st_mode)) != (0, 0, 0o700)
        or not stat.S_ISREG(database.st_mode)
        or stat.S_ISLNK(database.st_mode)
        or (database.st_uid, database.st_gid, stat.S_IMODE(database.st_mode)) != (0, 0, 0o600)
    ):
        raise InstalledPrivilegedVerificationError(
            "privileged database ownership or mode is unsafe"
        )
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        try:
            connection.execute("PRAGMA query_only=ON")
            return verify_privileged_broker_connection(connection)
        finally:
            connection.close()
    except (PrivilegedBrokerIntegrityError, sqlite3.Error) as exc:
        raise InstalledPrivilegedVerificationError(
            "privileged database verification failed"
        ) from exc


def require_installed_default_disabled(report: PrivilegedBrokerIntegrityReport) -> None:
    if (
        report.readiness not in {"uninitialized", "disabled"}
        or report.retains_authority
        or report.accepted_bindings
        or report.sealed_bindings
    ):
        raise InstalledPrivilegedVerificationError(
            "privileged capability is promoted or retains authority"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-default-disabled", action="store_true")
    parser.add_argument("--output", choices=("human", "json"), default="human")
    arguments = parser.parse_args(argv)
    try:
        report = verify_installed_database()
        if arguments.require_default_disabled:
            require_installed_default_disabled(report)
    except (InstalledPrivilegedVerificationError, OSError, sqlite3.Error) as exc:
        print(f"Privileged-broker verification failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    if arguments.output == "json":
        print(json.dumps(asdict(report), sort_keys=True, separators=(",", ":")))
    else:
        print(
            f"privileged revision={report.revision} readiness={report.readiness} "
            f"evidence_generation={report.evidence_generation}"
        )
    return 0


__all__ = [
    "InstalledPrivilegedVerificationError",
    "main",
    "require_installed_default_disabled",
    "verify_installed_database",
]
