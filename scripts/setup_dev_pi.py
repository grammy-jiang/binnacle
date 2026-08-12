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
EXECUTOR_SERVICE_NAME = "binnacle-executor.service"
EXECUTOR_SOCKET_NAME = "binnacle-executor.socket"
EXECUTOR_USER = "binnacle-executor"
EXECUTOR_GROUP = "binnacle-executor"
EXECUTOR_CLIENT_GROUP = "binnacle-executor-client"
EXECUTOR_TMPFILES_NAME = "binnacle-executor.conf"
GIT_CREDENTIAL_SERVICE_NAME = "binnacle-git-credential.service"
GIT_CREDENTIAL_SOCKET_NAME = "binnacle-git-credential.socket"
GIT_CREDENTIAL_USER = "binnacle-git-credential"
GIT_CREDENTIAL_GROUP = "binnacle-git-credential"
GIT_CREDENTIAL_CLIENT_GROUP = "binnacle-git-credential-client"
GIT_CREDENTIAL_TMPFILES_NAME = "binnacle-git-credential.conf"
PROBE_ROOT = Path("/var/lib/binnacle/probe-workspace")
SUPPORTED_PROBE_FILESYSTEM_TYPES = frozenset({"ext4"})
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
PROBE_WORKSPACE_PATHS = (
    (PROBE_ROOT, 0o700),
    (PROBE_ROOT / ".staging", 0o700),
)
EXECUTOR_ROOT_PATHS = (
    (Path("/etc/binnacle-executor"), 0o750),
    (Path("/var/lib/binnacle-executor"), 0o710),
)
EXECUTOR_STATE_PATHS = (
    (Path("/var/lib/binnacle-executor/state"), 0o700),
    (Path("/var/lib/binnacle-executor/output"), 0o700),
)
EXECUTOR_RUNTIME_ROOT_PATHS = ((Path("/run/binnacle-executor"), 0o710),)
EXECUTOR_RUNTIME_PRIVATE_PATHS = ((Path("/run/binnacle-executor/private"), 0o700),)
GIT_CREDENTIAL_ROOT_PATHS = (
    (Path("/etc/binnacle-git-credential"), 0o750),
    (Path("/var/lib/binnacle-git-credential"), 0o710),
)
GIT_CREDENTIAL_STATE_PATHS = ((Path("/var/lib/binnacle-git-credential/state"), 0o700),)
GIT_CREDENTIAL_RUNTIME_ROOT_PATHS = ((Path("/run/binnacle-git-credential"), 0o710),)
GIT_CREDENTIAL_RUNTIME_PRIVATE_PATHS = ((Path("/run/binnacle-git-credential/private"), 0o700),)
SYSTEM_PATHS = (
    *ROOT_PROTECTED_PATHS,
    *SERVICE_STATE_PATHS,
    *PROBE_WORKSPACE_PATHS,
    *EXECUTOR_ROOT_PATHS,
    *EXECUTOR_STATE_PATHS,
    *EXECUTOR_RUNTIME_ROOT_PATHS,
    *EXECUTOR_RUNTIME_PRIVATE_PATHS,
    *GIT_CREDENTIAL_ROOT_PATHS,
    *GIT_CREDENTIAL_STATE_PATHS,
    *GIT_CREDENTIAL_RUNTIME_ROOT_PATHS,
    *GIT_CREDENTIAL_RUNTIME_PRIVATE_PATHS,
)


def _same_gid_groups(group: grp.struct_group) -> tuple[grp.struct_group, ...]:
    """Return every local group entry granting the same numeric authority."""

    entries = tuple(candidate for candidate in grp.getgrall() if candidate.gr_gid == group.gr_gid)
    return entries or (group,)


def _effective_group_members(group: grp.struct_group) -> set[str]:
    """Return all supplementary and primary members of one numeric group."""

    supplementary = {member for candidate in _same_gid_groups(group) for member in candidate.gr_mem}
    return supplementary | {
        account.pw_name for account in pwd.getpwall() if account.pw_gid == group.gr_gid
    }


class SetupError(RuntimeError):
    """The requested setup is unsafe or does not match the fixed development profile."""


@dataclass(frozen=True, slots=True)
class Check:
    """One bounded setup preflight result."""

    name: str
    status: str
    summary: str


@dataclass(frozen=True, slots=True)
class _ProbeMountFacts:
    target: Path
    source: str
    filesystem_type: str
    options: frozenset[str]
    filesystem_root: str


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
        _check_probe_mount_profile(repo),
    )
    actions = (
        "ensure distinct application, executor, credential, client, and development groups",
        "ensure distinct non-root application, executor, and credential service users",
        "ensure binnacle has supplementary source-read group binnacle-dev",
        "grant application connect and executor parent-traverse access through the client group",
        "protect configuration/evaluation and create narrow application-owned kernel/probe state",
        "create separate executor config/state/output/runtime ownership roots",
        "create separate credential config/state/runtime ownership roots",
        "install application/executor/credential service, socket, and tmpfiles assets atomically",
        "leave executor and credential sockets/services disabled until candidate-Pi promotion",
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
    _ensure_group(EXECUTOR_GROUP)
    _ensure_group(EXECUTOR_CLIENT_GROUP)
    _ensure_group(GIT_CREDENTIAL_GROUP)
    _ensure_group(GIT_CREDENTIAL_CLIENT_GROUP)
    _ensure_user(SERVICE_USER, SERVICE_GROUP)
    _ensure_user(EXECUTOR_USER, EXECUTOR_GROUP)
    _ensure_user(GIT_CREDENTIAL_USER, GIT_CREDENTIAL_GROUP)
    subprocess.run(
        [
            "usermod",
            "--append",
            "--groups",
            f"{DEVELOPMENT_GROUP},{EXECUTOR_CLIENT_GROUP}",
            SERVICE_USER,
        ],
        check=True,
    )
    subprocess.run(
        [
            "usermod",
            "--append",
            "--groups",
            GIT_CREDENTIAL_CLIENT_GROUP,
            EXECUTOR_USER,
        ],
        check=True,
    )
    subprocess.run(
        [
            "usermod",
            "--append",
            "--groups",
            GIT_CREDENTIAL_CLIENT_GROUP,
            GIT_CREDENTIAL_USER,
        ],
        check=True,
    )
    subprocess.run(
        [
            "usermod",
            "--append",
            "--groups",
            f"{DEVELOPMENT_GROUP},{EXECUTOR_CLIENT_GROUP}",
            EXECUTOR_USER,
        ],
        check=True,
    )
    service_gid = grp.getgrnam(SERVICE_GROUP).gr_gid
    service_uid = pwd.getpwnam(SERVICE_USER).pw_uid
    executor_gid = grp.getgrnam(EXECUTOR_GROUP).gr_gid
    executor_uid = pwd.getpwnam(EXECUTOR_USER).pw_uid
    executor_client_gid = grp.getgrnam(EXECUTOR_CLIENT_GROUP).gr_gid
    credential_gid = grp.getgrnam(GIT_CREDENTIAL_GROUP).gr_gid
    credential_uid = pwd.getpwnam(GIT_CREDENTIAL_USER).pw_uid
    credential_client_gid = grp.getgrnam(GIT_CREDENTIAL_CLIENT_GROUP).gr_gid
    for path, mode in ROOT_PROTECTED_PATHS:
        _ensure_protected_directory(path, uid=0, gid=service_gid, mode=mode)
    for path, mode in SERVICE_STATE_PATHS:
        _ensure_protected_directory(path, uid=service_uid, gid=service_gid, mode=mode)
    for path, mode in PROBE_WORKSPACE_PATHS:
        _ensure_protected_directory(path, uid=service_uid, gid=service_gid, mode=mode)
    for path, mode in EXECUTOR_ROOT_PATHS:
        _ensure_protected_directory(path, uid=0, gid=executor_gid, mode=mode)
    for path, mode in EXECUTOR_STATE_PATHS:
        _ensure_protected_directory(path, uid=executor_uid, gid=executor_gid, mode=mode)
    for path, mode in EXECUTOR_RUNTIME_ROOT_PATHS:
        _ensure_protected_directory(path, uid=0, gid=executor_client_gid, mode=mode)
    for path, mode in EXECUTOR_RUNTIME_PRIVATE_PATHS:
        _ensure_protected_directory(path, uid=executor_uid, gid=executor_gid, mode=mode)
    for path, mode in GIT_CREDENTIAL_ROOT_PATHS:
        _ensure_protected_directory(path, uid=0, gid=credential_gid, mode=mode)
    for path, mode in GIT_CREDENTIAL_STATE_PATHS:
        _ensure_protected_directory(path, uid=credential_uid, gid=credential_gid, mode=mode)
    for path, mode in GIT_CREDENTIAL_RUNTIME_ROOT_PATHS:
        _ensure_protected_directory(path, uid=0, gid=credential_client_gid, mode=mode)
    for path, mode in GIT_CREDENTIAL_RUNTIME_PRIVATE_PATHS:
        _ensure_protected_directory(path, uid=credential_uid, gid=credential_gid, mode=mode)

    for name in (
        SERVICE_NAME,
        EXECUTOR_SERVICE_NAME,
        EXECUTOR_SOCKET_NAME,
        GIT_CREDENTIAL_SERVICE_NAME,
        GIT_CREDENTIAL_SOCKET_NAME,
    ):
        source = repo / "deploy/systemd" / name
        destination = Path("/etc/systemd/system") / name
        _atomic_install(source, destination, mode=0o644)
    _atomic_install(
        repo / "deploy/tmpfiles.d" / EXECUTOR_TMPFILES_NAME,
        Path("/etc/tmpfiles.d") / EXECUTOR_TMPFILES_NAME,
        mode=0o644,
    )
    _atomic_install(
        repo / "deploy/tmpfiles.d" / GIT_CREDENTIAL_TMPFILES_NAME,
        Path("/etc/tmpfiles.d") / GIT_CREDENTIAL_TMPFILES_NAME,
        mode=0o644,
    )
    subprocess.run(
        ["systemd-tmpfiles", "--create", f"/etc/tmpfiles.d/{EXECUTOR_TMPFILES_NAME}"],
        check=True,
    )
    subprocess.run(
        [
            "systemd-tmpfiles",
            "--create",
            f"/etc/tmpfiles.d/{GIT_CREDENTIAL_TMPFILES_NAME}",
        ],
        check=True,
    )
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
        canonical / "deploy/systemd" / EXECUTOR_SERVICE_NAME,
        canonical / "deploy/systemd" / EXECUTOR_SOCKET_NAME,
        canonical / "deploy/tmpfiles.d" / EXECUTOR_TMPFILES_NAME,
        canonical / "deploy/systemd" / GIT_CREDENTIAL_SERVICE_NAME,
        canonical / "deploy/systemd" / GIT_CREDENTIAL_SOCKET_NAME,
        canonical / "deploy/tmpfiles.d" / GIT_CREDENTIAL_TMPFILES_NAME,
    )
    if not required[0].exists() or any(not path.is_file() for path in required[1:]):
        return Check("repository", "fail", "repository is missing required tracked inputs")
    protected_roots = (Path("/etc"), Path("/var"), Path("/run"))
    if any(canonical.is_relative_to(root) for root in protected_roots):
        return Check("repository", "fail", "repository is under protected system state")
    return Check("repository", "pass", "canonical Git source checkout observed")


def _check_identity_compatibility() -> Check:
    groups: dict[str, grp.struct_group] = {}
    for name in (
        SERVICE_GROUP,
        DEVELOPMENT_GROUP,
        EXECUTOR_GROUP,
        EXECUTOR_CLIENT_GROUP,
        GIT_CREDENTIAL_GROUP,
        GIT_CREDENTIAL_CLIENT_GROUP,
    ):
        try:
            observed = grp.getgrnam(name)
        except KeyError:
            continue
        if observed.gr_gid == 0:
            return Check("identities", "fail", f"{name} group may not be root")
        groups[name] = observed
    if len({item.gr_gid for item in groups.values()}) != len(groups):
        return Check(
            "identities",
            "fail",
            "application, executor, credential, client, and development need distinct group IDs",
        )
    for protected_group_name in (GIT_CREDENTIAL_GROUP, GIT_CREDENTIAL_CLIENT_GROUP):
        protected_group = groups.get(protected_group_name)
        if protected_group is not None and tuple(
            candidate.gr_name for candidate in _same_gid_groups(protected_group)
        ) != (protected_group_name,):
            return Check(
                "identities",
                "fail",
                f"{protected_group_name} numeric group has an unexpected alias",
            )
    users: dict[str, pwd.struct_passwd] = {}
    for user_name, group_name in (
        (SERVICE_USER, SERVICE_GROUP),
        (EXECUTOR_USER, EXECUTOR_GROUP),
        (GIT_CREDENTIAL_USER, GIT_CREDENTIAL_GROUP),
    ):
        try:
            user = pwd.getpwnam(user_name)
        except KeyError:
            continue
        if user.pw_uid == 0:
            return Check("identities", "fail", f"{user_name} user may not be root")
        group = groups.get(group_name)
        if group is None or user.pw_gid != group.gr_gid:
            return Check("identities", "fail", f"{user_name} primary group is incompatible")
        users[user_name] = user
    if len({item.pw_uid for item in users.values()}) != len(users):
        return Check(
            "identities", "fail", "application, executor, and credential users must be distinct"
        )
    credential_user = users.get(GIT_CREDENTIAL_USER)
    if credential_user is not None:
        credential_uid_names = {credential_user.pw_name} | {
            account.pw_name
            for account in pwd.getpwall()
            if account.pw_uid == credential_user.pw_uid
        }
        if credential_uid_names != {GIT_CREDENTIAL_USER}:
            return Check(
                "identities",
                "fail",
                "Git credential-broker UID is shared by an unexpected identity",
            )
        credential_client_group = groups.get(GIT_CREDENTIAL_CLIENT_GROUP)
        allowed_credential_group_ids = {credential_user.pw_gid}
        if credential_client_group is not None:
            allowed_credential_group_ids.add(credential_client_group.gr_gid)
        try:
            credential_group_ids = set(os.getgrouplist(GIT_CREDENTIAL_USER, credential_user.pw_gid))
        except OSError:
            return Check(
                "identities",
                "fail",
                "Git credential-broker supplementary groups are unavailable",
            )
        if credential_group_ids != allowed_credential_group_ids:
            return Check(
                "identities",
                "fail",
                "Git credential-broker has an unexpected supplementary group",
            )
    credential_clients = groups.get(GIT_CREDENTIAL_CLIENT_GROUP)
    if credential_clients is not None:
        effective_credential_clients = _effective_group_members(credential_clients)
        denied_client_users = (SERVICE_USER, "binnacle-command")
        for denied_user_name in denied_client_users:
            try:
                pwd.getpwnam(denied_user_name)
            except KeyError:
                continue
            if denied_user_name in effective_credential_clients:
                return Check(
                    "identities",
                    "fail",
                    f"{denied_user_name} may not be a Git credential-broker client",
                )
        unexpected_clients = effective_credential_clients - {
            EXECUTOR_USER,
            GIT_CREDENTIAL_USER,
        }
        if unexpected_clients:
            return Check(
                "identities",
                "fail",
                "Git credential-broker client group contains an unexpected identity",
            )
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


def _check_probe_mount_profile(repo: Path) -> Check:
    """Reject unsafe probe aliases before setup changes any identity or mode."""

    inspection_target = PROBE_ROOT
    while not inspection_target.exists():
        parent = inspection_target.parent
        if parent == inspection_target:
            return Check("probe-mount", "fail", "probe mount ancestry is unavailable")
        inspection_target = parent
    try:
        observed = inspection_target.stat(follow_symlinks=False)
        mount = _parse_probe_mount_facts(
            _run_bounded(
                [
                    "findmnt",
                    "--json",
                    "--output",
                    "TARGET,SOURCE,FSTYPE,OPTIONS,FSROOT",
                    "--target",
                    str(inspection_target),
                ]
            )
        )
    except (OSError, subprocess.CalledProcessError, ValueError):
        return Check("probe-mount", "fail", "probe mount identity is unavailable")
    protected_devices: set[int] = set()
    for path in (
        repo,
        Path("/etc/binnacle"),
        Path("/var/lib/binnacle/state"),
        Path("/var/lib/binnacle/results"),
        Path("/var/lib/binnacle/audit"),
        Path("/var/lib/binnacle/evaluation"),
    ):
        try:
            protected_devices.add(path.stat(follow_symlinks=False).st_dev)
        except OSError:
            continue
    if not _probe_mount_is_supported(
        mount,
        root_device=observed.st_dev,
        protected_devices=frozenset(protected_devices),
    ):
        return Check(
            "probe-mount",
            "fail",
            "probe mount is not the reviewed block-backed ext4 profile",
        )
    return Check("probe-mount", "pass", "reviewed block-backed ext4 profile observed")


def _parse_probe_mount_facts(value: str) -> _ProbeMountFacts:
    document = json.loads(value)
    if not isinstance(document, dict):
        raise ValueError("findmnt output is not an object")
    filesystems = document.get("filesystems")
    if not isinstance(filesystems, list) or len(filesystems) != 1:
        raise ValueError("findmnt did not return exactly one filesystem")
    raw = filesystems[0]
    if not isinstance(raw, dict):
        raise ValueError("findmnt filesystem entry is not an object")
    target = raw.get("target")
    source = raw.get("source")
    filesystem_type = raw.get("fstype")
    options = raw.get("options")
    filesystem_root = raw.get("fsroot")
    if (
        not isinstance(target, str)
        or not target
        or len(target) > 4096
        or not isinstance(source, str)
        or not source
        or len(source) > 4096
        or not isinstance(filesystem_type, str)
        or not filesystem_type
        or len(filesystem_type) > 4096
        or not isinstance(options, str)
        or not options
        or len(options) > 4096
        or not isinstance(filesystem_root, str)
        or not filesystem_root
        or len(filesystem_root) > 4096
    ):
        raise ValueError("findmnt filesystem fields are invalid")
    target_path = Path(target)
    if not target_path.is_absolute() or target_path != Path(os.path.normpath(target)):
        raise ValueError("findmnt target is not a canonical absolute path")
    return _ProbeMountFacts(
        target=target_path,
        source=source,
        filesystem_type=filesystem_type.casefold(),
        options=frozenset(item.casefold() for item in options.split(",") if item),
        filesystem_root=filesystem_root,
    )


def _probe_mount_is_supported(
    mount: _ProbeMountFacts,
    *,
    root_device: int,
    protected_devices: frozenset[int],
) -> bool:
    target_contains_root = mount.target == PROBE_ROOT or PROBE_ROOT.is_relative_to(mount.target)
    block_source = mount.source.startswith("/dev/") or mount.source.startswith(
        ("UUID=", "LABEL=", "PARTUUID=", "PARTLABEL=")
    )
    if (
        not target_contains_root
        or mount.filesystem_type not in SUPPORTED_PROBE_FILESYSTEM_TYPES
        or "rw" not in mount.options
        or {"ro", "bind", "rbind"} & mount.options
        or mount.filesystem_root != "/"
        or "[" in mount.source
        or "]" in mount.source
        or not block_source
    ):
        return False
    return not (mount.target == PROBE_ROOT and root_device in protected_devices)


def _run_bounded(command: list[str]) -> str:
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if len(result.stdout.encode("utf-8")) > 65_536:
        raise ValueError("command output exceeded setup bound")
    return result.stdout.strip()


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


def _ensure_user(name: str, primary_group: str) -> None:
    try:
        pwd.getpwnam(name)
    except KeyError:
        subprocess.run(
            [
                "useradd",
                "--system",
                "--gid",
                primary_group,
                "--home-dir",
                "/nonexistent",
                "--shell",
                "/usr/sbin/nologin",
                name,
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
