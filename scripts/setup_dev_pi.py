#!/usr/bin/env python3
"""Idempotently prepare the fixed Binnacle development-Pi service layout."""

from __future__ import annotations

import argparse
import grp
import json
import os
import platform
import pwd
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

CANONICAL_REPO = Path("/srv/binnacle-dev/repo")
SERVICE_NAME = "binnacle-dev.service"
SERVICE_USER = "binnacle"
SERVICE_GROUP = "binnacle"
DEVELOPMENT_GROUP = "binnacle-dev"
ROOT_PROTECTED_PATHS = (
    (Path("/etc/binnacle"), 0o750),
    (Path("/var/lib/binnacle"), 0o750),
    (Path("/var/lib/binnacle/evaluation"), 0o750),
)
SERVICE_STATE_PATHS = (
    (Path("/var/lib/binnacle/state"), 0o750),
    (Path("/var/lib/binnacle/state/checkpoints"), 0o750),
    (Path("/var/lib/binnacle/state/audit-obligations"), 0o750),
    (Path("/var/lib/binnacle/results"), 0o750),
    (Path("/var/lib/binnacle/results/objects"), 0o750),
    (Path("/var/lib/binnacle/results/streams"), 0o750),
    (Path("/var/lib/binnacle/results/tmp"), 0o750),
    (Path("/var/lib/binnacle/audit"), 0o750),
    (Path("/var/lib/binnacle/audit/epochs"), 0o750),
    (Path("/var/lib/binnacle/audit/emergency"), 0o750),
)
SYSTEM_PATHS = (*ROOT_PROTECTED_PATHS, *SERVICE_STATE_PATHS)


class SetupError(RuntimeError):
    """The requested setup is unsafe or does not match the fixed development profile."""


@dataclass(frozen=True, slots=True)
class Check:
    """One bounded setup preflight result."""

    name: str
    status: str
    summary: str


@dataclass(frozen=True, slots=True)
class SetupPlan:
    """Deterministic preflight plus the finite actions ``apply`` may perform."""

    checks: tuple[Check, ...]
    actions: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return all(check.status == "pass" for check in self.checks)


def build_setup_plan(repo: Path) -> SetupPlan:
    """Perform all read-only production preflight checks."""

    checks = (
        _check_platform(),
        _check_architecture(),
        _check_distribution(),
        _check_python(),
        _check_systemd(),
        _check_repository(repo),
        _check_identity_compatibility(),
        _check_system_path_safety(),
    )
    actions = (
        "ensure system groups binnacle and binnacle-dev",
        "ensure non-root service user binnacle with primary group binnacle",
        "ensure binnacle has supplementary source-read group binnacle-dev",
        "protect configuration/evaluation and create narrow application-owned kernel state",
        "install binnacle-dev.service atomically",
        "run systemctl daemon-reload",
    )
    return SetupPlan(checks=checks, actions=actions)


def apply_setup(repo: Path, *, enable: bool) -> SetupPlan:
    """Apply only the declared finite setup after a successful preflight."""

    plan = build_setup_plan(repo)
    if not plan.ready:
        raise SetupError("setup preflight failed; no changes were made")
    if os.geteuid() != 0:
        raise SetupError("apply requires root")

    _ensure_group(SERVICE_GROUP)
    _ensure_group(DEVELOPMENT_GROUP)
    _ensure_user()
    subprocess.run(
        ["usermod", "--append", "--groups", DEVELOPMENT_GROUP, SERVICE_USER],
        check=True,
    )
    service_gid = grp.getgrnam(SERVICE_GROUP).gr_gid
    service_uid = pwd.getpwnam(SERVICE_USER).pw_uid
    for path, mode in ROOT_PROTECTED_PATHS:
        _ensure_protected_directory(path, uid=0, gid=service_gid, mode=mode)
    for path, mode in SERVICE_STATE_PATHS:
        _ensure_protected_directory(path, uid=service_uid, gid=service_gid, mode=mode)

    source = repo / "deploy/systemd" / SERVICE_NAME
    destination = Path("/etc/systemd/system") / SERVICE_NAME
    _atomic_install(source, destination, mode=0o644)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    if enable:
        subprocess.run(["systemctl", "enable", SERVICE_NAME], check=True)
    return plan


def _check_platform() -> Check:
    if platform.system() != "Linux":
        return Check("platform", "fail", "Linux is required")
    return Check("platform", "pass", "Linux observed")


def _check_architecture() -> Check:
    machine = platform.machine().casefold()
    if sys.maxsize <= 2**32 or machine not in {"aarch64", "arm64"}:
        return Check("architecture", "fail", "a 64-bit ARM development Pi is required")
    return Check("architecture", "pass", "64-bit ARM observed")


def _check_distribution() -> Check:
    try:
        values = _read_os_release(Path("/etc/os-release"))
    except OSError:
        return Check("distribution", "fail", "os-release could not be read")
    identifiers = {values.get("ID", ""), *values.get("ID_LIKE", "").split()}
    if not identifiers & {"debian", "raspbian", "ubuntu"}:
        return Check("distribution", "fail", "a reviewed Debian-family profile is required")
    return Check("distribution", "pass", "Debian-family profile observed")


def _check_python() -> Check:
    if not (3, 11) <= sys.version_info[:2] < (3, 14):
        return Check("python", "fail", "Python 3.11 through 3.13 is required")
    return Check("python", "pass", f"Python {sys.version_info.major}.{sys.version_info.minor}")


def _check_systemd() -> Check:
    if shutil.which("systemctl") is None or not Path("/run/systemd/system").is_dir():
        return Check("systemd", "fail", "a running systemd system manager is required")
    return Check("systemd", "pass", "systemd manager observed")


def _check_repository(repo: Path) -> Check:
    try:
        canonical = repo.resolve(strict=True)
    except OSError:
        return Check("repository", "fail", "repository path does not exist")
    if canonical != CANONICAL_REPO:
        return Check("repository", "fail", "repository must be /srv/binnacle-dev/repo")
    required = (
        canonical / ".git",
        canonical / "pyproject.toml",
        canonical / "uv.lock",
        canonical / "deploy/systemd" / SERVICE_NAME,
    )
    if not required[0].exists() or any(not path.is_file() for path in required[1:]):
        return Check("repository", "fail", "repository is missing required tracked inputs")
    protected_roots = (Path("/etc"), Path("/var"), Path("/run"))
    if any(canonical.is_relative_to(root) for root in protected_roots):
        return Check("repository", "fail", "repository is under protected system state")
    return Check("repository", "pass", "canonical Git source checkout observed")


def _check_identity_compatibility() -> Check:
    try:
        service_group = grp.getgrnam(SERVICE_GROUP)
        if service_group.gr_gid == 0:
            return Check("identities", "fail", "binnacle group may not be root")
    except KeyError:
        service_group = None
    try:
        development_group = grp.getgrnam(DEVELOPMENT_GROUP)
        if development_group.gr_gid == 0:
            return Check("identities", "fail", "binnacle-dev group may not be root")
    except KeyError:
        development_group = None
    try:
        user = pwd.getpwnam(SERVICE_USER)
    except KeyError:
        user = None
    if (
        service_group is not None
        and development_group is not None
        and service_group.gr_gid == development_group.gr_gid
    ):
        return Check(
            "identities",
            "fail",
            "binnacle and binnacle-dev must have distinct group IDs",
        )
    if user is not None:
        if user.pw_uid == 0:
            return Check("identities", "fail", "binnacle user may not be root")
        if service_group is None or user.pw_gid != service_group.gr_gid:
            return Check("identities", "fail", "binnacle primary group is incompatible")
    return Check("identities", "pass", "existing identities are compatible or absent")


def _check_system_path_safety() -> Check:
    for path, _ in SYSTEM_PATHS:
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current /= part
            try:
                info = current.lstat()
            except FileNotFoundError:
                break
            except OSError:
                return Check("system-paths", "fail", "system path metadata is unavailable")
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                return Check(
                    "system-paths",
                    "fail",
                    "a protected system path component is unsafe",
                )
    return Check("system-paths", "pass", "protected system path components are safe")


def _ensure_protected_directory(path: Path, *, uid: int, gid: int, mode: int) -> None:
    """Create one fixed absolute directory without following any path-component symlink."""

    if not path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts[1:]):
        raise SetupError("protected directory path is not canonical and absolute")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                os.mkdir(part, mode=0o750, dir_fd=descriptor)
                child = os.open(part, flags, dir_fd=descriptor)
            except OSError as exc:
                raise SetupError("protected directory path contains an unsafe component") from exc
            os.close(descriptor)
            descriptor = child
        os.fchown(descriptor, uid, gid)
        os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)


def _ensure_group(name: str) -> None:
    try:
        grp.getgrnam(name)
    except KeyError:
        subprocess.run(["groupadd", "--system", name], check=True)


def _ensure_user() -> None:
    try:
        pwd.getpwnam(SERVICE_USER)
    except KeyError:
        subprocess.run(
            [
                "useradd",
                "--system",
                "--gid",
                SERVICE_GROUP,
                "--home-dir",
                "/nonexistent",
                "--shell",
                "/usr/sbin/nologin",
                SERVICE_USER,
            ],
            check=True,
        )


def _atomic_install(source: Path, destination: Path, *, mode: int) -> None:
    data = source.read_bytes()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}-",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(mode)
        os.chown(temporary, 0, 0)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _read_os_release(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and name in {"ID", "ID_LIKE"}:
            values[name] = value.strip().strip('"')
    return values


def _render(plan: SetupPlan, *, output: str) -> None:
    if output == "json":
        print(
            json.dumps(
                {
                    "ready": plan.ready,
                    "checks": [asdict(check) for check in plan.checks],
                    "actions": list(plan.actions),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return
    for check in plan.checks:
        print(f"{check.status.upper():4} {check.name}: {check.summary}")
    print("Planned actions:")
    for action in plan.actions:
        print(f"- {action}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("check", "apply"):
        child = commands.add_parser(command)
        child.add_argument("--repo", type=Path, required=True)
        child.add_argument("--output", choices=("human", "json"), default="human")
        if command == "apply":
            child.add_argument("--enable", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run read-only preflight or the finite privileged setup."""

    arguments = _parser().parse_args(argv)
    try:
        plan = (
            build_setup_plan(arguments.repo)
            if arguments.command == "check"
            else apply_setup(arguments.repo, enable=arguments.enable)
        )
    except (OSError, SetupError, subprocess.CalledProcessError) as exc:
        print(f"setup error: {exc}", file=sys.stderr)
        return 2
    _render(plan, output=arguments.output)
    if arguments.command == "apply":
        print("Next: sync the locked environment, install protected config, then verify.")
    return 0 if plan.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
