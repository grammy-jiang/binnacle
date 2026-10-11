"""Private, inode-bound runtime roots; no persisted marker grants authority.

The threat boundary is a cooperative user account. Same-UID malicious writers
can copy secrets and race pathnames; this is not a sandbox against that account.
Runtime data is ephemeral and must never contain durable job history.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from weakref import WeakSet

from binnacle.platform.contracts.capability_contracts import (
    AuthorityUnknown,
    Capability,
    CapabilityState,
    GenerationMismatch,
    NativeCapabilityError,
    PermissionDenied,
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


def _identity(fd: int, name: str) -> tuple[int, int]:
    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    return info.st_dev, info.st_ino


def _endpoint(fd: int, name: str, expected: tuple[int, int]) -> None:
    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if (
        (info.st_dev, info.st_ino) != expected
        or not stat.S_ISSOCK(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise _refuse("ipc_endpoint_changed")


def _credentials(fd: int, name: str, lease: ServiceLease) -> dict[str, Any]:
    key_fd = private_file(fd, name + ".auth")
    try:
        value = bounded_json(os.read(key_fd, 65537))
    finally:
        os.close(key_fd)
    if not isinstance(value, dict) or value.get("generation") != lease.generation:
        raise _refuse("ipc_generation_mismatch")
    if value.get("label") != lease.label or value.get("uid") != lease.uid:
        raise _refuse()
    return value


def _lock_root(fd: int, *, create: bool = True) -> int:
    lock = os.open(
        "manager.lock",
        os.O_RDWR | (os.O_CREAT if create else 0) | os.O_NOFOLLOW | os.O_NONBLOCK,
        0o600,
        dir_fd=fd,
    )
    try:
        info = os.fstat(lock)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise denied("ipc_lock_unsafe")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if _identity(fd, "manager.lock") != (info.st_dev, info.st_ino):
            raise _refuse("ipc_lock_changed")
        return lock
    except (OSError, NativeCapabilityError) as exc:
        os.close(lock)
        raise _refuse("ipc_duplicate_starter") from exc


def _refuse(code: str = "ipc_authentication_refused") -> PermissionDenied:
    return PermissionDenied(code, Capability(CapabilityState.UNKNOWN, code, _SCOPE))


def bounded_json(data: bytes) -> dict[str, Any]:
    """Bound allocation and nesting before invoking the recursive JSON decoder."""
    if len(data) > 1024 * 1024:
        raise _refuse("ipc_frame_too_large")
    depth, quoted, escaped = 0, False, False
    for byte in data:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > 32:
                raise _refuse("ipc_frame_too_deep")
        elif byte in (93, 125):
            depth -= 1
    try:
        value = json.loads(data)
    except (ValueError, RecursionError) as exc:
        raise _refuse("ipc_frame_invalid") from exc
    if not isinstance(value, dict):
        raise _refuse("ipc_frame_invalid")
    return value


@dataclass(frozen=True, eq=False)
class EndpointRecovery:
    """Process-local evidence of a completed native peer + generation handshake.

    Keep this object before a crash. Files/serialized tokens cannot recreate it.
    PID reuse deliberately refuses recovery; this never grants signal authority.
    """

    path: Path
    lease: ServiceLease
    peer_pid: int
    issuer_pid: int
    identities: tuple[tuple[int, int], ...]
    credentials_digest: bytes


_RECOVERY: WeakSet[EndpointRecovery] = WeakSet()


def _remember_endpoint(
    path: Path,
    lease: ServiceLease,
    credentials: dict[str, Any],
    identities: tuple[tuple[int, int], ...],
) -> EndpointRecovery:
    token = EndpointRecovery(
        path,
        lease,
        credentials["pid"],
        os.getpid(),
        identities,
        _credential_digest(credentials),
    )
    _RECOVERY.add(token)
    return token


def _credential_digest(value: dict[str, Any]) -> bytes:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).digest()


def recover_stale_endpoint(authority: EndpointRecovery) -> None:
    """Reclaim only a previously authenticated generation whose PID is absent.

    Under the singleton lock, revalidate the root, socket, credential contents and lock
    inode captured by the live handshake. ESRCH is required; permission errors,
    live/reused PIDs, replacements and copied evidence preserve every entry.
    A new server must open a fresh generation after recovery. No job authority
    is recovered. Cooperative same-UID writers remain outside this guarantee.
    """
    if authority not in _RECOVERY or authority.issuer_pid != os.getpid():
        raise _refuse("ipc_recovery_not_authenticated")
    path, lease = authority.path, authority.lease
    fd = validate_lease(path.parent, lease)
    lock = -1
    try:
        lock = _lock_root(fd, create=False)
        names = (path.name, path.name + ".auth", "manager.lock")
        current = tuple(_identity(fd, name) for name in names)
        value = _credentials(fd, path.name, lease)
        if (
            current != authority.identities
            or _credential_digest(value) != authority.credentials_digest
        ):
            raise _refuse("ipc_recovery_identity_changed")
        _endpoint(fd, path.name, current[0])
        if type(authority.peer_pid) is not int or authority.peer_pid <= 0:
            raise _refuse("ipc_recovery_peer_invalid")
        try:
            os.kill(authority.peer_pid, 0)  # existence probe, never delivers a signal
        except ProcessLookupError:
            pass
        else:
            raise _refuse("ipc_recovery_peer_not_absent")
        # Validate both identities before either unlink; replacements are not ours.
        if tuple(_identity(fd, name) for name in names) != current:
            raise _refuse("ipc_recovery_identity_changed")
        for name, identity in zip(names[:2], current[:2], strict=True):
            if not unlink_owned(fd, name, identity):
                raise _refuse("ipc_recovery_identity_changed")
        _RECOVERY.discard(authority)
    except OSError as exc:
        code = "ipc_recovery_unverified"
        raise AuthorityUnknown(
            code, Capability(CapabilityState.UNKNOWN, code, _SCOPE)
        ) from exc
    finally:
        if lock >= 0:
            os.close(lock)
        os.close(fd)
