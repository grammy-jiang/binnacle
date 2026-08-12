#!/usr/bin/env python3
"""Read-only verification of the isolated executor store, with a temporary CI lane."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import stat
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import quote

from alembic import command
from alembic.config import Config

from binnacle.domain.execution import EXECUTOR_PROTOCOL_VERSION
from binnacle.executor.integrity import (
    ExecutorIntegrityError,
    verify_executor_connection,
)
from binnacle.executor.state import (
    EXECUTOR_REVISION,
    ExecutorStoreIdentity,
    ExecutorStoreSettings,
    open_executor_store,
)


class ExecutorVerificationError(RuntimeError):
    """Executor state is unavailable, incompatible, or contradictory."""


@dataclass(frozen=True, slots=True)
class ExecutorVerification:
    revision: str
    integrity: str
    readiness: str
    schema_generation: int
    evidence_generation: int
    accepted_executions: int
    outstanding_executions: int
    pending_cancels: int
    no_accept_tombstones: int


def verify_executor_database(path: Path) -> ExecutorVerification:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ExecutorVerificationError("executor database is unavailable") from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or path.name != "executor-state.sqlite3"
        or metadata.st_uid != os.geteuid()
        or metadata.st_gid != os.getegid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise ExecutorVerificationError("executor database path is unsafe")
    uri = f"file:{quote(str(path))}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise ExecutorVerificationError("executor database could not be opened read-only") from exc
    try:
        connection.execute("PRAGMA query_only=ON")
        report = verify_executor_connection(connection, expected_revision=EXECUTOR_REVISION)
        if report.readiness not in {"uninitialized", "ready"} or report.outstanding_executions:
            raise ExecutorVerificationError("executor database identity or integrity failed")
        return ExecutorVerification(
            revision=report.revision,
            integrity="ok",
            readiness=report.readiness,
            schema_generation=report.schema_generation,
            evidence_generation=report.evidence_generation,
            accepted_executions=report.accepted_executions,
            outstanding_executions=report.outstanding_executions,
            pending_cancels=report.pending_cancels,
            no_accept_tombstones=report.no_accept_tombstones,
        )
    except (ExecutorIntegrityError, sqlite3.Error, TypeError, ValueError) as exc:
        raise ExecutorVerificationError("executor database verification failed") from exc
    finally:
        connection.close()


def verify_executor_paths(database: Path, runtime_directory: Path) -> None:
    expected = (
        (database.parent, 0o700),
        (runtime_directory, 0o700),
    )
    for path, mode in expected:
        try:
            metadata = path.stat(follow_symlinks=False)
        except OSError as exc:
            raise ExecutorVerificationError("executor private directory is unavailable") from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
            or stat.S_IMODE(metadata.st_mode) != mode
        ):
            raise ExecutorVerificationError("executor private directory ownership is unsafe")


async def _temporary_verification(repo_root: Path) -> ExecutorVerification:
    with tempfile.TemporaryDirectory(prefix="binnacle-executor-verify-") as temporary:
        root = Path(temporary)
        state = root / "state"
        runtime = root / "run"
        state.mkdir(mode=0o700)
        runtime.mkdir(mode=0o700)
        database = state / "executor-state.sqlite3"
        config = Config(repo_root / "alembic-executor.ini")
        config.set_main_option("script_location", str(repo_root / "migrations_executor"))
        config.attributes["database_url"] = f"sqlite:///{database}"
        command.upgrade(config, "head")
        database.chmod(0o600)
        store = await open_executor_store(
            settings=ExecutorStoreSettings(
                path=database,
                runtime_directory=runtime,
                verify_permissions=False,
            ),
            identity=ExecutorStoreIdentity(
                supervisor_instance_id="temporary-verifier",
                boot_id_digest="1" * 64,
                protocol_version=EXECUTOR_PROTOCOL_VERSION,
                build_sha256="2" * 64,
                profile_sha256="3" * 64,
            ),
        )
        await store.close()
        return verify_executor_database(database)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--temporary", action="store_true")
    source.add_argument("--database", type=Path)
    parser.add_argument(
        "--runtime-directory",
        type=Path,
        default=Path("/run/binnacle-executor/private"),
    )
    parser.add_argument("--output", choices=("human", "json"), default="human")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.temporary:
            result = asyncio.run(_temporary_verification(Path(__file__).resolve().parents[1]))
        else:
            assert arguments.database is not None
            verify_executor_paths(arguments.database, arguments.runtime_directory)
            result = verify_executor_database(arguments.database)
    except (ExecutorVerificationError, OSError, sqlite3.Error) as exc:
        print(f"executor verification failed: {type(exc).__name__}")
        return 1
    if arguments.output == "json":
        print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
    else:
        print(
            f"executor revision={result.revision} integrity={result.integrity} "
            f"readiness={result.readiness} evidence_generation={result.evidence_generation}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
