"""Protected, closed configuration for the independent executor service."""

from __future__ import annotations

import hashlib
import os
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path

from binnacle.domain.execution import validate_sha256

_MAX_CONFIG_BYTES = 65_536


class ExecutorConfigError(RuntimeError):
    """Executor configuration is absent, unsafe, or outside the frozen profile."""


@dataclass(frozen=True, slots=True)
class ExecutorSettings:
    database_path: Path
    runtime_directory: Path
    output_directory: Path
    expected_application_uid: int
    expected_application_gid: int
    build_sha256: str
    profile_sha256: str
    busy_timeout_ms: int = 5_000

    def __post_init__(self) -> None:
        if self.database_path != Path("/var/lib/binnacle-executor/state/executor-state.sqlite3"):
            raise ExecutorConfigError("executor database path is not the protected path")
        if self.runtime_directory != Path("/run/binnacle-executor/private"):
            raise ExecutorConfigError("executor runtime path is not the protected path")
        if self.output_directory != Path("/var/lib/binnacle-executor/output"):
            raise ExecutorConfigError("executor output path is not the protected path")
        if min(self.expected_application_uid, self.expected_application_gid) < 1:
            raise ExecutorConfigError("executor application peer identity is invalid")
        if not 100 <= self.busy_timeout_ms <= 60_000:
            raise ExecutorConfigError("executor busy timeout is outside the safe range")
        try:
            validate_sha256(self.build_sha256, name="build_sha256")
            validate_sha256(self.profile_sha256, name="profile_sha256")
        except ValueError as exc:
            raise ExecutorConfigError("executor runtime digest is invalid") from exc


def load_executor_settings(
    path: Path,
    *,
    expected_owner_uid: int = 0,
    expected_group_gid: int | None = None,
) -> ExecutorSettings:
    group_gid = os.getegid() if expected_group_gid is None else expected_group_gid
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != expected_owner_uid
            or metadata.st_gid != group_gid
            or stat.S_IMODE(metadata.st_mode) != 0o640
        ):
            raise ExecutorConfigError("executor config ownership or mode is unsafe")
        if not metadata.st_size <= _MAX_CONFIG_BYTES:
            raise ExecutorConfigError("executor config exceeds the reviewed limit")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            document = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ExecutorConfigError("executor config could not be loaded") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if set(document) != {"executor"} or not isinstance(document["executor"], dict):
        raise ExecutorConfigError("executor config root fields are not exact")
    values = document["executor"]
    expected = {
        "database_path",
        "runtime_directory",
        "output_directory",
        "expected_application_uid",
        "expected_application_gid",
        "build_sha256",
        "profile_sha256",
        "busy_timeout_ms",
    }
    if set(values) != expected:
        raise ExecutorConfigError("executor config fields are not exact")
    return ExecutorSettings(
        database_path=Path(_text(values, "database_path")),
        runtime_directory=Path(_text(values, "runtime_directory")),
        output_directory=Path(_text(values, "output_directory")),
        expected_application_uid=_integer(values, "expected_application_uid"),
        expected_application_gid=_integer(values, "expected_application_gid"),
        build_sha256=_text(values, "build_sha256"),
        profile_sha256=_text(values, "profile_sha256"),
        busy_timeout_ms=_integer(values, "busy_timeout_ms"),
    )


def boot_id_digest(path: Path = Path("/proc/sys/kernel/random/boot_id")) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ExecutorConfigError("kernel boot identity is unavailable") from exc
    if not 1 <= len(raw) <= 128:
        raise ExecutorConfigError("kernel boot identity is invalid")
    return hashlib.sha256(raw.strip()).hexdigest()


def _text(value: dict[str, object], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str):
        raise ExecutorConfigError(f"executor {name} must be text")
    return result


def _integer(value: dict[str, object], name: str) -> int:
    result = value.get(name)
    if isinstance(result, bool) or not isinstance(result, int):
        raise ExecutorConfigError(f"executor {name} must be an integer")
    return result


__all__ = [
    "ExecutorConfigError",
    "ExecutorSettings",
    "boot_id_digest",
    "load_executor_settings",
]
