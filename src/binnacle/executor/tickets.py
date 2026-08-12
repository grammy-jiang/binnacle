"""Fail-closed validation of exact execution tickets before durable acceptance."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from binnacle.domain.execution import ExecutionTicket, ResourcePlan, canonical_sha256

_FORBIDDEN_MODE_BITS: Final = stat.S_ISUID | stat.S_ISGID


class ExecutionTicketRejected(RuntimeError):
    """A ticket is expired, incompatible, or no longer names the reviewed executable."""


@dataclass(frozen=True, slots=True)
class ExecutableIdentity:
    path: str
    device: int
    inode: int
    mode: int
    owner_uid: int
    owner_gid: int
    size: int
    modified_ns: int
    content_sha256: str
    identity_sha256: str


@dataclass(frozen=True, slots=True)
class CommandProfileBinding:
    """Exact receiver-owned plan facts for one promoted command profile."""

    workspace_id: str
    workspace_profile_sha256: str
    workspace_root_identity_sha256: str
    workspace_mount_identity_sha256: str
    policy_sha256: str
    mount_plan_id: str
    mount_plan_sha256: str
    sandbox_profile_id: str
    sandbox_plan_sha256: str
    process_isolation_profile_id: str
    process_isolation_plan_sha256: str
    network_profile_id: str
    network_plan_sha256: str
    listener_exposure: str
    environment_sha256: str
    permitted_cwd_sha256: frozenset[str]
    permitted_argv_prefixes: tuple[tuple[str, ...], ...]
    resource_maximum: ResourcePlan
    permitted_environment_names: frozenset[str]
    permitted_input_modes: frozenset[str]

    def __post_init__(self) -> None:
        if (
            not self.permitted_environment_names
            or not self.permitted_cwd_sha256
            or not self.permitted_argv_prefixes
        ):
            raise ExecutionTicketRejected("command profile environment allowlist is empty")
        if not self.permitted_input_modes or not self.permitted_input_modes <= {
            "none",
            "inline",
            "reference",
            "workspace_script",
        }:
            raise ExecutionTicketRejected("command profile input modes are invalid")


@dataclass(frozen=True, slots=True)
class TicketValidationProfile:
    boot_id_digest: str
    command_profiles: Mapping[str, CommandProfileBinding]
    permitted_executables: Mapping[str, str]
    maximum_ticket_lifetime_seconds: int = 300

    def __post_init__(self) -> None:
        if self.maximum_ticket_lifetime_seconds < 1 or self.maximum_ticket_lifetime_seconds > 3600:
            raise ExecutionTicketRejected("ticket lifetime ceiling is invalid")
        if not self.permitted_executables or not self.command_profiles:
            raise ExecutionTicketRejected("ticket profile has no reviewed executable")


class ExecutionTicketValidator:
    """Revalidate ticket time, profile selections, and executable identity."""

    def __init__(
        self,
        profile: TicketValidationProfile,
        *,
        wall_clock: Callable[[], datetime] | None = None,
        monotonic_clock_ns: Callable[[], int] | None = None,
    ) -> None:
        self._profile = profile
        self._wall_clock = wall_clock or (lambda: datetime.now(UTC))
        self._monotonic_clock_ns = monotonic_clock_ns or time.monotonic_ns

    def validate(self, ticket: ExecutionTicket) -> ExecutableIdentity:
        now = self._wall_clock()
        if now.tzinfo is None:
            raise ExecutionTicketRejected("executor wall clock is not timezone-aware")
        if ticket.boot_id_digest != self._profile.boot_id_digest:
            raise ExecutionTicketRejected("ticket boot identity is stale")
        if not ticket.issued_at <= now < ticket.expires_at:
            raise ExecutionTicketRejected("ticket is not current")
        if self._monotonic_clock_ns() >= ticket.monotonic_deadline_ns:
            raise ExecutionTicketRejected("ticket monotonic deadline elapsed")
        lifetime = (ticket.expires_at - ticket.issued_at).total_seconds()
        if lifetime > self._profile.maximum_ticket_lifetime_seconds:
            raise ExecutionTicketRejected("ticket lifetime exceeds the selected profile")
        binding = self._profile.command_profiles.get(ticket.command_profile_id)
        if binding is None:
            raise ExecutionTicketRejected("ticket command profile is not promoted")
        exact_facts = (
            (ticket.workspace_id, binding.workspace_id),
            (ticket.workspace_profile_sha256, binding.workspace_profile_sha256),
            (ticket.workspace_root_identity_sha256, binding.workspace_root_identity_sha256),
            (ticket.workspace_mount_identity_sha256, binding.workspace_mount_identity_sha256),
            (ticket.policy_sha256, binding.policy_sha256),
            (ticket.mount_plan_id, binding.mount_plan_id),
            (ticket.mount_plan_sha256, binding.mount_plan_sha256),
            (ticket.sandbox_profile_id, binding.sandbox_profile_id),
            (ticket.sandbox_plan_sha256, binding.sandbox_plan_sha256),
            (ticket.process_isolation_profile_id, binding.process_isolation_profile_id),
            (ticket.process_isolation_plan_sha256, binding.process_isolation_plan_sha256),
            (ticket.network_profile_id, binding.network_profile_id),
            (ticket.network_plan_sha256, binding.network_plan_sha256),
            (ticket.listener_exposure, binding.listener_exposure),
        )
        if any(observed != expected for observed, expected in exact_facts):
            raise ExecutionTicketRejected("ticket authority plan differs from the selected profile")
        if any(
            observed > maximum
            for observed, maximum in zip(
                ticket.resource_plan.to_wire().values(),
                binding.resource_maximum.to_wire().values(),
                strict=True,
            )
        ):
            raise ExecutionTicketRejected("ticket resources exceed the selected profile")
        environment_names = {name for name, _value in ticket.environment}
        if (
            not environment_names <= binding.permitted_environment_names
            or ticket.environment_sha256 != binding.environment_sha256
        ):
            raise ExecutionTicketRejected("ticket environment is outside the explicit allowlist")
        if ticket.cwd_sha256 not in binding.permitted_cwd_sha256:
            raise ExecutionTicketRejected("ticket cwd is not selected by the profile")
        if not any(
            ticket.argv[: len(prefix)] == prefix for prefix in binding.permitted_argv_prefixes
        ):
            raise ExecutionTicketRejected("ticket argv is outside the selected profile")
        input_mode = _ticket_input_mode(ticket)
        if input_mode not in binding.permitted_input_modes:
            raise ExecutionTicketRejected("ticket input mode is not selected by the profile")
        expected = self._profile.permitted_executables.get(ticket.executable_path)
        if expected is None or expected != ticket.executable_identity_sha256:
            raise ExecutionTicketRejected("ticket executable is not selected by the profile")
        observed = inspect_executable(Path(ticket.executable_path))
        if observed.identity_sha256 != expected:
            raise ExecutionTicketRejected("ticket executable identity changed")
        return observed


def inspect_executable(path: Path) -> ExecutableIdentity:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ExecutionTicketRejected("reviewed executable cannot be opened safely") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ExecutionTicketRejected("reviewed executable is not a regular file")
        if metadata.st_mode & _FORBIDDEN_MODE_BITS:
            raise ExecutionTicketRejected("set-id executable is not permitted")
        if metadata.st_mode & 0o111 == 0:
            raise ExecutionTicketRejected("reviewed executable is not executable")
        try:
            capability = os.getxattr(descriptor, "security.capability")
        except OSError as exc:
            if exc.errno not in {errno.ENODATA, errno.ENOTSUP, errno.EOPNOTSUPP}:
                raise ExecutionTicketRejected(
                    "executable capabilities cannot be inspected"
                ) from exc
        else:
            if capability:
                raise ExecutionTicketRejected("capability-bearing executable is not permitted")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 128 * 1024):
            digest.update(chunk)
        content_sha256 = digest.hexdigest()
        document = {
            "content_sha256": content_sha256,
            "device": metadata.st_dev,
            "inode": metadata.st_ino,
            "mode": stat.S_IMODE(metadata.st_mode),
            "modified_ns": metadata.st_mtime_ns,
            "owner_gid": metadata.st_gid,
            "owner_uid": metadata.st_uid,
            "path": str(path),
            "size": metadata.st_size,
        }
        return ExecutableIdentity(
            path=str(path),
            device=metadata.st_dev,
            inode=metadata.st_ino,
            mode=stat.S_IMODE(metadata.st_mode),
            owner_uid=metadata.st_uid,
            owner_gid=metadata.st_gid,
            size=metadata.st_size,
            modified_ns=metadata.st_mtime_ns,
            content_sha256=content_sha256,
            identity_sha256=canonical_sha256(document),
        )
    finally:
        os.close(descriptor)


__all__ = [
    "CommandProfileBinding",
    "ExecutableIdentity",
    "ExecutionTicketRejected",
    "ExecutionTicketValidator",
    "TicketValidationProfile",
    "inspect_executable",
]


def _ticket_input_mode(ticket: ExecutionTicket) -> str:
    if ticket.inline_stdin is not None:
        return "inline"
    if ticket.stdin_reference_sha256 is not None:
        return "reference"
    if ticket.workspace_script_sha256 is not None:
        return "workspace_script"
    return "none"
