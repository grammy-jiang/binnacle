#!/usr/bin/env python3
"""Read-only credential-broker verification, with an isolated temporary CI lane."""

from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
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


_CONFIG_DIRECTORY = Path("/etc/binnacle-git-credential")
_CONFIG_FILE = _CONFIG_DIRECTORY / "broker.toml"
_PERSISTENT_ROOT = Path("/var/lib/binnacle-git-credential")
_STATE_DIRECTORY = _PERSISTENT_ROOT / "state"
_DATABASE = _STATE_DIRECTORY / "git-credential-evidence.sqlite3"
_RUNTIME_ROOT = Path("/run/binnacle-git-credential")
_RUNTIME_PRIVATE = _RUNTIME_ROOT / "private"
_SOCKET = _RUNTIME_ROOT / "broker.sock"
_TMPFILES = Path("/etc/tmpfiles.d/binnacle-git-credential.conf")


def _effective_group_members(group: grp.struct_group) -> set[str]:
    """Return supplementary and primary members of one local group."""

    return set(group.gr_mem) | {
        account.pw_name for account in pwd.getpwall() if account.pw_gid == group.gr_gid
    }


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


def verify_default_disabled_foundation() -> None:
    """Verify the broker-owned private half of the unpromoted deployment boundary."""

    try:
        application = pwd.getpwnam("binnacle")
        executor = pwd.getpwnam("binnacle-executor")
        credential = pwd.getpwnam("binnacle-git-credential")
        credential_group = grp.getgrnam("binnacle-git-credential")
        client_group = grp.getgrnam("binnacle-git-credential-client")
    except KeyError as exc:
        raise GitCredentialBrokerVerificationError(
            "credential foundation identities are unavailable"
        ) from exc
    if os.geteuid() != credential.pw_uid or os.getegid() != credential_group.gr_gid:
        raise GitCredentialBrokerVerificationError(
            "foundation verification must run as the credential identity"
        )
    members = _effective_group_members(client_group)
    credential_uid_names = {credential.pw_name} | {
        account.pw_name for account in pwd.getpwall() if account.pw_uid == credential.pw_uid
    }
    process_group_ids = {os.getegid(), *os.getgroups()}
    if (
        credential.pw_gid != credential_group.gr_gid
        or credential.pw_uid in {0, application.pw_uid, executor.pw_uid}
        or credential_uid_names != {"binnacle-git-credential"}
        or process_group_ids != {credential_group.gr_gid, client_group.gr_gid}
        or client_group.gr_gid in {0, credential_group.gr_gid}
        or members != {"binnacle-executor", "binnacle-git-credential"}
        or application.pw_gid == client_group.gr_gid
    ):
        raise GitCredentialBrokerVerificationError(
            "credential foundation identity boundary differs"
        )
    try:
        command = pwd.getpwnam("binnacle-command")
    except KeyError:
        command = None
    if command is not None and (
        command.pw_gid == client_group.gr_gid or "binnacle-command" in members
    ):
        raise GitCredentialBrokerVerificationError(
            "command identity may not be a credential-broker client"
        )

    expected_directories = {
        _CONFIG_DIRECTORY: (0, credential_group.gr_gid, 0o750),
        _PERSISTENT_ROOT: (0, credential_group.gr_gid, 0o710),
        _STATE_DIRECTORY: (credential.pw_uid, credential_group.gr_gid, 0o700),
        _RUNTIME_ROOT: (0, client_group.gr_gid, 0o710),
        _RUNTIME_PRIVATE: (credential.pw_uid, credential_group.gr_gid, 0o700),
    }
    for path, expected in expected_directories.items():
        try:
            metadata = path.stat(follow_symlinks=False)
        except OSError as exc:
            raise GitCredentialBrokerVerificationError(
                "credential foundation directory is unavailable"
            ) from exc
        observed = (metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode))
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or observed != expected
        ):
            raise GitCredentialBrokerVerificationError(
                "credential foundation directory ownership is unsafe"
            )
    for path in (_CONFIG_FILE, _DATABASE, _SOCKET):
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise GitCredentialBrokerVerificationError(
                "credential disabled-state path is unavailable"
            ) from exc
        raise GitCredentialBrokerVerificationError(
            "credential authority or listener exists before promotion"
        )
    try:
        tmpfiles_metadata = _TMPFILES.stat(follow_symlinks=False)
        tmpfiles_lines = frozenset(_TMPFILES.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeError) as exc:
        raise GitCredentialBrokerVerificationError(
            "credential tmpfiles policy is unavailable"
        ) from exc
    if (
        stat.S_ISLNK(tmpfiles_metadata.st_mode)
        or not stat.S_ISREG(tmpfiles_metadata.st_mode)
        or (
            tmpfiles_metadata.st_uid,
            tmpfiles_metadata.st_gid,
            stat.S_IMODE(tmpfiles_metadata.st_mode),
        )
        != (0, 0, 0o644)
        or tmpfiles_lines
        != {
            "# Type Path Mode User Group Age Argument",
            "d /run/binnacle-git-credential 0710 root binnacle-git-credential-client -",
            "d /run/binnacle-git-credential/private 0700 "
            "binnacle-git-credential binnacle-git-credential -",
            "d /var/lib/binnacle-git-credential 0710 root binnacle-git-credential -",
            "d /var/lib/binnacle-git-credential/state 0700 "
            "binnacle-git-credential binnacle-git-credential -",
        }
    ):
        raise GitCredentialBrokerVerificationError("credential tmpfiles policy differs")


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
    source.add_argument("--foundation-only", action="store_true")
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
    report: CredentialBrokerIntegrityReport | None
    try:
        if arguments.foundation_only:
            verify_default_disabled_foundation()
            report = None
        elif arguments.temporary:
            report = temporary_verification(Path(__file__).resolve().parents[1])
        else:
            assert arguments.database is not None
            verify_paths(arguments.database, arguments.runtime_directory)
            report = verify_database(arguments.database)
    except (GitCredentialBrokerVerificationError, OSError, sqlite3.Error) as exc:
        print(f"Git credential-broker verification failed: {type(exc).__name__}")
        return 1
    if arguments.output == "json":
        value = (
            {"readiness": "default_disabled", "status": "pass"}
            if report is None
            else asdict(report)
        )
        print(json.dumps(value, sort_keys=True, separators=(",", ":")))
    else:
        if report is None:
            print("credential foundation readiness=default_disabled")
        else:
            print(
                f"credential revision={report.revision} readiness={report.readiness} "
                f"evidence_generation={report.evidence_generation}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
