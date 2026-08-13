"""Protected configuration for the independently installed privileged broker."""

from __future__ import annotations

import hashlib
import os
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

DEFAULT_PRIVILEGED_CONFIG_PATH: Final = Path("/etc/binnacle-privileged/broker.toml")
_DATABASE_PATH: Final = Path("/var/lib/binnacle-privileged/evidence.db")
_RUNTIME_DIRECTORY: Final = Path("/run/binnacle-privileged")
_MAX_CONFIG_BYTES: Final = 65_536


class PrivilegedBrokerConfigError(RuntimeError):
    """The broker configuration is absent, unsafe, or outside the frozen profile."""


@dataclass(frozen=True, slots=True)
class PrivilegedBrokerSettings:
    database_path: Path
    runtime_directory: Path
    runtime_group_gid: int
    expected_application_uid: int
    expected_application_gid: int
    build_sha256: str
    profile_sha256: str
    acceptance_enabled: bool
    busy_timeout_ms: int = 5_000

    def __post_init__(self) -> None:
        if self.database_path != _DATABASE_PATH:
            raise PrivilegedBrokerConfigError("privileged database path is not protected")
        if self.runtime_directory != _RUNTIME_DIRECTORY:
            raise PrivilegedBrokerConfigError("privileged runtime path is not protected")
        if (
            min(
                self.runtime_group_gid,
                self.expected_application_uid,
                self.expected_application_gid,
            )
            < 1
        ):
            raise PrivilegedBrokerConfigError("privileged peer or runtime identity is invalid")
        if not 100 <= self.busy_timeout_ms <= 60_000:
            raise PrivilegedBrokerConfigError("privileged busy timeout is outside the safe range")
        if self.acceptance_enabled:
            raise PrivilegedBrokerConfigError(
                "privileged effect acceptance is not promoted in this implementation"
            )
        for value in (self.build_sha256, self.profile_sha256):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise PrivilegedBrokerConfigError("privileged runtime digest is invalid")


def load_privileged_broker_settings(
    path: Path,
    *,
    expected_path: Path = DEFAULT_PRIVILEGED_CONFIG_PATH,
    expected_owner_uid: int = 0,
    expected_group_gid: int = 0,
) -> PrivilegedBrokerSettings:
    """Load one exact root-owned configuration without following a final symlink."""

    if path != expected_path or not path.is_absolute():
        raise PrivilegedBrokerConfigError("privileged config path is not the protected path")
    try:
        parent = path.parent.lstat()
    except OSError as exc:
        raise PrivilegedBrokerConfigError("privileged config parent is unavailable") from exc
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_ISLNK(parent.st_mode)
        or parent.st_uid != expected_owner_uid
        or parent.st_gid != expected_group_gid
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise PrivilegedBrokerConfigError("privileged config parent ownership or mode is unsafe")

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
            or metadata.st_gid != expected_group_gid
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise PrivilegedBrokerConfigError("privileged config ownership or mode is unsafe")
        if not metadata.st_size <= _MAX_CONFIG_BYTES:
            raise PrivilegedBrokerConfigError("privileged config exceeds the reviewed limit")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            document = tomllib.load(stream)
    except PrivilegedBrokerConfigError:
        raise
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PrivilegedBrokerConfigError("privileged config could not be loaded") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    if set(document) != {"broker"} or not isinstance(document["broker"], dict):
        raise PrivilegedBrokerConfigError("privileged config root fields are not exact")
    values = document["broker"]
    expected = {
        "acceptance_enabled",
        "build_sha256",
        "busy_timeout_ms",
        "database_path",
        "expected_application_gid",
        "expected_application_uid",
        "profile_sha256",
        "runtime_directory",
        "runtime_group_gid",
    }
    if set(values) != expected:
        raise PrivilegedBrokerConfigError("privileged config fields are not exact")
    return PrivilegedBrokerSettings(
        database_path=Path(_text(values, "database_path")),
        runtime_directory=Path(_text(values, "runtime_directory")),
        runtime_group_gid=_integer(values, "runtime_group_gid"),
        expected_application_uid=_integer(values, "expected_application_uid"),
        expected_application_gid=_integer(values, "expected_application_gid"),
        build_sha256=_text(values, "build_sha256"),
        profile_sha256=_text(values, "profile_sha256"),
        acceptance_enabled=_boolean(values, "acceptance_enabled"),
        busy_timeout_ms=_integer(values, "busy_timeout_ms"),
    )


def boot_id_sha256(path: Path = Path("/proc/sys/kernel/random/boot_id")) -> str:
    """Return only a digest of the kernel boot identity."""

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PrivilegedBrokerConfigError("kernel boot identity is unavailable") from exc
    if not 1 <= len(raw) <= 128 or not raw.strip():
        raise PrivilegedBrokerConfigError("kernel boot identity is invalid")
    return hashlib.sha256(raw.strip()).hexdigest()


def _text(value: dict[str, object], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str):
        raise PrivilegedBrokerConfigError(f"privileged {name} must be text")
    return result


def _integer(value: dict[str, object], name: str) -> int:
    result = value.get(name)
    if isinstance(result, bool) or not isinstance(result, int):
        raise PrivilegedBrokerConfigError(f"privileged {name} must be an integer")
    return result


def _boolean(value: dict[str, object], name: str) -> bool:
    result = value.get(name)
    if not isinstance(result, bool):
        raise PrivilegedBrokerConfigError(f"privileged {name} must be a boolean")
    return result


__all__ = [
    "DEFAULT_PRIVILEGED_CONFIG_PATH",
    "PrivilegedBrokerConfigError",
    "PrivilegedBrokerSettings",
    "boot_id_sha256",
    "load_privileged_broker_settings",
]
