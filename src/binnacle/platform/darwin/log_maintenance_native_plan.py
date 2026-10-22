"""Advisory, side-effect-free Issue #30 launchd operation plan.

A proposed command is NOT an authorization to run it. A future independent
privileged helper must re-attest the installed root-owned plist, client
authority, exact launchd generation, guardian, and writer quiescence itself.
No executable entrypoint, sudo, shell, subprocess, or service control exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from binnacle.platform.darwin.log_maintenance_installed_identity import (
    InstalledIdentityRefused,
    InstalledWriterIdentity,
    _names,
)

_ACTIONS = frozenset({"stop", "restore"})
_NONCE = re.compile(r"^[a-f0-9]{32}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")
_PLIST_ROOT = Path("/Library/LaunchDaemons")


class NativePlanRefused(RuntimeError):
    """An advisory plan cannot represent an untrusted native operation."""


@dataclass(frozen=True)
class NativeActuatorPlan:
    """A non-executable review artifact, never a privilege or deletion grant."""

    action: Literal["stop", "restore"]
    label: str
    launchd_target: str
    plist_path: Path
    raw_path: Path
    plist_sha256: str
    transaction_nonce: str
    controller_generation: str
    source_device: int
    source_inode: int
    argv: tuple[str, ...]
    production_authorized: bool = False

    def __post_init__(self) -> None:
        if self.production_authorized:
            raise ValueError("an advisory launchd plan never grants authority")


def build_native_actuator_plan(
    identity: InstalledWriterIdentity,
    *,
    action: str,
    approved_plist_sha256: str,
    transaction_nonce: str,
    controller_generation: str,
    expected_source: tuple[int, int],
    approved_logs_root: Path,
) -> NativeActuatorPlan:
    """Validate pinned *claims* and generate exact argv without executing it.

    All arguments remain caller-controlled here. Neither this function nor
    the InstalledWriterIdentity dataclass authenticates a privileged peer.
    A native helper must independently obtain and recheck every claim.
    """
    if not isinstance(identity, InstalledWriterIdentity):
        raise NativePlanRefused("installed writer identity missing")
    if (
        not isinstance(identity.label, str)
        or not isinstance(identity.launchd_target, str)
        or not isinstance(identity.plist_digest, str)
        or not isinstance(identity.plist_path, Path)
        or not isinstance(identity.raw_path, Path)
    ):
        raise NativePlanRefused("malformed installed writer identity")
    if (
        not isinstance(action, str)
        or action not in _ACTIONS
        or not isinstance(approved_plist_sha256, str)
        or _SHA.fullmatch(approved_plist_sha256) is None
        or identity.plist_digest != approved_plist_sha256
        or not isinstance(transaction_nonce, str)
        or _NONCE.fullmatch(transaction_nonce) is None
        or not isinstance(controller_generation, str)
        or _NONCE.fullmatch(controller_generation) is None
        or transaction_nonce == controller_generation
        or not isinstance(expected_source, tuple)
        or len(expected_source) != 2
        or any(type(item) is not int or item <= 0 for item in expected_source)
        or (identity.raw_device, identity.raw_inode) != expected_source
        or not isinstance(approved_logs_root, Path)
        or not approved_logs_root.is_absolute()
        or ".." in approved_logs_root.parts
        or identity.raw_path.parent != approved_logs_root
        or type(identity.raw_size) is not int
        or identity.raw_size <= 0
        or type(identity.plist_device) is not int
        or identity.plist_device <= 0
        or type(identity.plist_inode) is not int
        or identity.plist_inode <= 0
        or identity.production_authorized
    ):
        raise NativePlanRefused("native plan identity or transaction mismatch")
    label = identity.label
    try:
        _names(label, identity.raw_path.name)
    except InstalledIdentityRefused as exc:
        raise NativePlanRefused("unrecognized installed service or source") from exc
    if (
        identity.launchd_target != f"system/{label}"
        or identity.plist_path != _PLIST_ROOT / f"{label}.plist"
        or not identity.raw_path.is_absolute()
        or ".." in identity.raw_path.parts
        or identity.raw_path.parent.parts[-3:] != ("Library", "Logs", "binnacle")
        or identity.raw_path.parent == identity.plist_path.parent
        or "\x00" in str(identity.raw_path)
    ):
        raise NativePlanRefused("native plan contains a foreign path or target")
    argv: tuple[str, ...]
    approved_action: Literal["stop", "restore"]
    if action == "stop":
        approved_action = "stop"
        argv = ("/bin/launchctl", "bootout", identity.launchd_target)
    else:
        approved_action = "restore"
        argv = (
            "/bin/launchctl",
            "bootstrap",
            "system",
            str(identity.plist_path),
        )
    return NativeActuatorPlan(
        approved_action,
        label,
        identity.launchd_target,
        identity.plist_path,
        identity.raw_path,
        approved_plist_sha256,
        transaction_nonce,
        controller_generation,
        expected_source[0],
        expected_source[1],
        argv,
    )
