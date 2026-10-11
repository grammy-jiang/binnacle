"""Private, inode-bound runtime roots; no persisted marker grants authority.

The threat boundary is a cooperative user account. Same-UID malicious writers
can copy secrets and race pathnames; this is not a sandbox against that account.
Runtime data is ephemeral and must never contain durable job history.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from binnacle.platform.contracts.capability_contracts import (
    Capability,
    CapabilityState,
    GenerationMismatch,
    UnsafePath,
)
from binnacle.platform.contracts.native_service_contracts import ServiceLease
from binnacle.platform.contracts.runtime_path_contracts import RuntimePaths

_ROOTS: dict[ServiceLease, Path] = {}
_SCOPE = "private cooperative-account runtime; no durable job authority"


def denied(code: str) -> UnsafePath:
    return UnsafePath(code, Capability(CapabilityState.UNAVAILABLE, code, _SCOPE))


def check_socket_path(path: Path) -> None:
    # sockaddr_un.sun_path is 104 bytes on Darwin, including the terminator.
    if not path.is_absolute() or len(os.fsencode(path)) >= 104:
        raise denied("runtime_socket_path_invalid")


def open_private_root(root: Path, *, create: bool = False) -> int:
    """Walk from / with O_NOFOLLOW, retaining an opened final directory.

    Root-owned sticky temp ancestors are permitted. All other ancestors must
    be root/current-user owned and not writable by another account. The final
    root must be exactly 0700 and current-user owned.
    """
    if not root.is_absolute() or ".." in root.parts or root == Path("/"):
        raise denied("runtime_root_invalid")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in root.parts[1:]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
            if info.st_uid not in (0, os.getuid()) or (
                info.st_mode & 0o022 and not sticky_root
            ):
                raise denied("runtime_ancestor_untrusted")
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise denied("runtime_root_not_private")
        return fd
    except (OSError, UnsafePath) as exc:
        os.close(fd)
        raise denied("runtime_root_unsafe") from exc


def resolve_runtime_paths() -> RuntimePaths:
    configured = os.environ.get("BINNACLE_RUNTIME_DIR")
    root = (
        Path(configured) if configured else Path.home() / "Library/Caches/Binnacle/r3"
    )
    check_socket_path(root / "jobs.sock")
    fd = open_private_root(root, create=True)
    os.close(fd)
    return RuntimePaths(root, root / "jobs.sock")


def open_service_lease(*, root: Path, label: str, generation: str) -> ServiceLease:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", label):
        raise denied("service_label_invalid")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", generation):
        raise denied("service_generation_invalid")
    check_socket_path(root / "jobs.sock")
    fd = open_private_root(root)
    try:
        info = os.fstat(fd)
        lease = ServiceLease(os.getuid(), label, generation, info.st_dev, info.st_ino)
        _ROOTS[lease] = root
        return lease
    finally:
        os.close(fd)


def lease_root(lease: ServiceLease) -> Path:
    """Lookup only a root opened in this process; a copied lease is insufficient."""
    root = _ROOTS.get(lease)
    if root is None:
        raise denied("service_lease_not_opened")
    fd = validate_lease(root, lease)
    os.close(fd)
    return root


def validate_lease(root: Path, lease: ServiceLease) -> int:
    fd = open_private_root(root)
    info = os.fstat(fd)
    if (lease.uid, lease.root_device, lease.root_inode) != (
        os.getuid(),
        info.st_dev,
        info.st_ino,
    ):
        os.close(fd)
        raise GenerationMismatch(
            "service_root_changed",
            Capability(CapabilityState.UNKNOWN, "service_root_changed", _SCOPE),
        )
    return fd


def private_file(fd: int, name: str) -> int:
    """Open a bounded private regular file, refusing links and hard links."""
    result = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    info = os.fstat(result)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
        or info.st_size > 65536
    ):
        os.close(result)
        raise denied("runtime_file_unsafe")
    return result


def unlink_owned(fd: int, name: str, identity: tuple[int, int]) -> bool:
    """Never adopt stale entries; callers hold the singleton lock through cleanup.

    The identity check covers accidental pathname replacement. The cooperative
    account assumption is essential: POSIX has no conditional inode unlink.
    """
    try:
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return True
    if (info.st_dev, info.st_ino) != identity:
        return False
    os.unlink(name, dir_fd=fd)
    return True
