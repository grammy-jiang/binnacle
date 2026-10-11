"""Test-owned Darwin provisioning transaction over an injected launchd lifecycle."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from binnacle.deployment.darwin.plist import (
    DEFAULT_ROLE,
    render_plist,
    validate_plist_bytes,
    validate_test_label,
)

_SCOPE = "test-owned launchd label under an explicit private root"


@dataclass(frozen=True)
class Capability:
    """Local mirror of the native capability value; B0 maps it at composition."""

    state: str  # "LIMITED" | "UNAVAILABLE"; never AVAILABLE for this lane
    reason_code: str
    scope: str


@dataclass(frozen=True)
class ServiceLease:
    uid: int
    label: str
    generation: str
    root_device: int
    root_inode: int


@dataclass(frozen=True)
class ServicePlan:
    lease: ServiceLease
    plist_bytes: bytes
    plist_path: Path
    expected_previous_sha256: str | None


@dataclass(frozen=True)
class ServiceReceipt:
    lease: ServiceLease
    action: str
    capability: Capability
    absent: bool


class ProvisionError(RuntimeError):
    """Controlled error carrying a sanitized code, never native stderr or paths."""

    def __init__(self, code: str, capability: Capability) -> None:
        self.code = code
        self.capability = capability
        super().__init__(code)


class CapabilityUnavailable(ProvisionError): ...


class GenerationMismatch(ProvisionError): ...


class UnsafePath(ProvisionError): ...


class ApplyUnknown(ProvisionError):
    """Bootstrap may have loaded the label; the plist is kept for owned bootout."""


_LIMITED = Capability("LIMITED", "test_owned_user_domain_only", _SCOPE)
_UNAVAILABLE = Capability("UNAVAILABLE", "launchd_lifecycle_missing", _SCOPE)
_UNKNOWN = Capability("UNKNOWN", "apply_partial_label_may_be_loaded", _SCOPE)


class LaunchdLifecycle(Protocol):
    """Subset of A3's service lifecycle that A6 consumes; A6 never runs launchctl."""

    def bootstrap(self, label: str, plist_path: Path) -> None: ...

    def bootout(self, label: str) -> None: ...

    def is_absent(self, label: str) -> bool:
        """True only if the label, its children and its socket are all gone."""
        ...


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


def _is_private_dir(st: os.stat_result, uid: int) -> bool:
    return stat.S_ISDIR(st.st_mode) and st.st_uid == uid and not st.st_mode & 0o077


def open_private_root(root: Path, uid: int) -> int:
    """Open the root by pathname exactly once; the descriptor is the authority."""
    try:
        fd = os.open(root, _DIR_FLAGS)
    except OSError:
        raise UnsafePath("root_unusable", _LIMITED) from None
    if not _is_private_dir(os.fstat(fd), uid):
        os.close(fd)
        raise UnsafePath("root_not_private", _LIMITED)
    return fd


def open_private_subdir(root_fd: int, name: str, uid: int) -> int:
    """Create or open ``name`` under ``root_fd`` as an owned 0700 real directory."""
    try:
        os.mkdir(name, 0o700, dir_fd=root_fd)
    except FileExistsError:
        pass
    except OSError:
        raise UnsafePath("subdir_unusable", _LIMITED) from None
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=root_fd)
    except OSError:
        raise UnsafePath("subdir_not_private", _LIMITED) from None
    if not _is_private_dir(os.fstat(fd), uid):
        os.close(fd)
        raise UnsafePath("subdir_not_private", _LIMITED)
    return fd


@contextmanager
def pinned_root(root: Path, uid: int) -> Iterator[int]:
    """Yield a descriptor for the private root; closed on exit."""
    fd = open_private_root(root, uid)
    try:
        yield fd
    finally:
        os.close(fd)


@contextmanager
def pinned_subdir(root_fd: int, name: str, uid: int) -> Iterator[int]:
    fd = open_private_subdir(root_fd, name, uid)
    try:
        yield fd
    finally:
        os.close(fd)


def read_regular_at(
    dir_fd: int, name: str, *, private_uid: int | None = None
) -> bytes | None:
    """Read a regular file by nofollow, descriptor-relative open; None if absent."""
    try:
        fd = os.open(name, _FILE_FLAGS, dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    except OSError:
        raise UnsafePath("plist_not_regular_file", _LIMITED) from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise UnsafePath("plist_not_regular_file", _LIMITED)
        if private_uid is not None and (st.st_uid != private_uid or st.st_mode & 0o077):
            raise UnsafePath("plan_file_not_private", _LIMITED)
        with os.fdopen(os.dup(fd), "rb") as fh:
            return fh.read()
    finally:
        os.close(fd)


def unlink_at(dir_fd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=dir_fd)
    except FileNotFoundError:
        pass


def write_atomic_at(dir_fd: int, name: str, data: bytes) -> None:
    """Write ``name`` via a 0600 temp file and descriptor-relative rename."""
    tmp = f".{name}.tmp{os.getpid()}"
    fd = os.open(
        tmp,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=dir_fd,
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except BaseException:
        unlink_at(dir_fd, tmp)
        raise


def _identity(st: os.stat_result) -> tuple[int, int]:
    return (st.st_dev, st.st_ino)


class DarwinProvisioner:
    """Plan, apply and roll back one test-owned plist inside a private root.

    Every filesystem effect goes through descriptors opened ``O_NOFOLLOW`` from
    one pinned root descriptor, so a rename/symlink swap of the root pathname or
    of ``backups`` after validation cannot redirect reads or writes. The only
    pathname handoff is launchd's bootstrap path, which is re-verified to still
    name the object we wrote immediately before the call.
    """

    def __init__(
        self, root: Path, *, uid: int, lifecycle: LaunchdLifecycle | None
    ) -> None:
        self._root = root
        self._uid = uid
        self._lifecycle = lifecycle

    @property
    def plist_dir(self) -> Path:
        """A3 accepts only plists directly inside the private runtime root."""
        return self._root

    @property
    def backup_dir(self) -> Path:
        return self._root / "backups"

    @contextmanager
    def _pin(self, lease: ServiceLease) -> Iterator[int]:
        validate_test_label(lease.label)
        if lease.uid != self._uid:
            raise GenerationMismatch("uid_mismatch", _LIMITED)
        with pinned_root(self._root, self._uid) as fd:
            if _identity(os.fstat(fd)) != (lease.root_device, lease.root_inode):
                raise GenerationMismatch("root_identity_mismatch", _LIMITED)
            yield fd

    def _plist_path(self, label: str) -> Path:
        return self.plist_dir / f"{label}.plist"

    def _backup_name(self, label: str) -> str:
        return f"{label}.prior"

    def plan(
        self,
        lease: ServiceLease,
        *,
        argv: Sequence[str],
        environment: Mapping[str, str],
        workdir: Path,
        role: str = DEFAULT_ROLE,
    ) -> ServicePlan:
        with self._pin(lease) as root_fd:
            path = self._plist_path(lease.label)
            data = render_plist(
                lease.label,
                argv=argv,
                environment=environment,
                workdir=workdir,
                runtime_dir=self._root,
                role=role,
            )
            prior = read_regular_at(root_fd, path.name)
        return ServicePlan(
            lease, data, path, None if prior is None else sha256_hex(prior)
        )

    def _revalidate(self, root_fd: int, plan: ServicePlan) -> bytes | None:
        if plan.plist_path != self._plist_path(plan.lease.label):
            raise UnsafePath("plist_path_not_owned", _LIMITED)
        return read_regular_at(root_fd, plan.plist_path.name)

    def _verify_handoff(self, root_fd: int, plan: ServicePlan) -> None:
        """The pathname launchd will open must still be the object we wrote."""
        name = plan.plist_path.name
        try:
            held = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            root_now = os.lstat(self._root)
            named = os.lstat(plan.plist_path)
        except OSError:
            raise UnsafePath("handoff_path_moved", _LIMITED) from None
        if (
            _identity(root_now) != _identity(os.fstat(root_fd))
            or not stat.S_ISREG(named.st_mode)
            or _identity(named) != _identity(held)
        ):
            raise UnsafePath("handoff_path_moved", _LIMITED)

    def apply(self, plan: ServicePlan) -> ServiceReceipt:
        if self._lifecycle is None:
            raise CapabilityUnavailable("launchd_lifecycle_missing", _UNAVAILABLE)
        with self._pin(plan.lease) as root_fd:
            current = self._revalidate(root_fd, plan)
            current_sha = None if current is None else sha256_hex(current)
            if current_sha != plan.expected_previous_sha256:
                raise GenerationMismatch("previous_digest_mismatch", _LIMITED)
            try:
                validate_plist_bytes(
                    plan.plist_bytes, label=plan.lease.label, runtime_dir=self._root
                )
            except ValueError:
                raise UnsafePath("plist_scope_refused", _LIMITED) from None
            label = plan.lease.label
            name = plan.plist_path.name
            with pinned_subdir(root_fd, "backups", self._uid) as backups_fd:
                if current is not None:
                    write_atomic_at(backups_fd, self._backup_name(label), current)
                write_atomic_at(root_fd, name, plan.plist_bytes)
                if read_regular_at(root_fd, name) != plan.plist_bytes:
                    self._restore(root_fd, plan, current)
                    raise UnsafePath("plist_persist_mismatch", _LIMITED)
                try:
                    self._verify_handoff(root_fd, plan)
                except UnsafePath:
                    self._restore(root_fd, plan, current)
                    unlink_at(backups_fd, self._backup_name(label))
                    raise
                try:
                    self._lifecycle.bootstrap(label, plan.plist_path)
                except BaseException as exc:
                    self._after_failed_bootstrap(
                        self._lifecycle, root_fd, backups_fd, plan, current, exc
                    )
                    raise
        return ServiceReceipt(plan.lease, "apply", _LIMITED, absent=False)

    def _after_failed_bootstrap(
        self,
        lifecycle: LaunchdLifecycle,
        root_fd: int,
        backups_fd: int,
        plan: ServicePlan,
        prior: bytes | None,
        exc: BaseException,
    ) -> None:
        """Never leave a loaded label without its plist.

        Retry teardown through the owned label; only a verified-absent label
        lets the prior state be restored. Otherwise keep the new plist (so
        rollback still owns the label) and report typed UNKNOWN.
        """
        label = plan.lease.label
        try:
            lifecycle.bootout(label)
            absent = lifecycle.is_absent(label)
        except Exception:  # noqa: BLE001 - any teardown failure means not proven absent
            absent = False
        if absent:
            self._restore(root_fd, plan, prior)
            unlink_at(backups_fd, self._backup_name(label))
            return
        raise ApplyUnknown("apply_partial_label_may_be_loaded", _UNKNOWN) from exc

    def _restore(self, root_fd: int, plan: ServicePlan, prior: bytes | None) -> None:
        if prior is None:
            unlink_at(root_fd, plan.plist_path.name)
        else:
            write_atomic_at(root_fd, plan.plist_path.name, prior)

    def rollback(self, plan: ServicePlan) -> ServiceReceipt:
        if self._lifecycle is None:
            raise CapabilityUnavailable("launchd_lifecycle_missing", _UNAVAILABLE)
        with self._pin(plan.lease) as root_fd:
            current = self._revalidate(root_fd, plan)
            label = plan.lease.label
            if (
                current is not None
                and plan.expected_previous_sha256 is not None
                and sha256_hex(current) == plan.expected_previous_sha256
                and current != plan.plist_bytes
            ):
                # Already rolled back to the exact prior bytes: idempotent.
                absent = self._lifecycle.is_absent(label)
                return ServiceReceipt(plan.lease, "rollback", _LIMITED, absent=absent)
            if current is not None and sha256_hex(current) != sha256_hex(
                plan.plist_bytes
            ):
                # Foreign bytes: preserve them and do not unload someone else's job.
                raise GenerationMismatch("foreign_plist_preserved", _LIMITED)
            self._lifecycle.bootout(label)
            if not self._lifecycle.is_absent(label):
                # Keep the plist so a retry still owns and can finish the teardown.
                return ServiceReceipt(plan.lease, "rollback", _LIMITED, absent=False)
            with pinned_subdir(root_fd, "backups", self._uid) as backups_fd:
                prior: bytes | None = None
                if plan.expected_previous_sha256 is not None:
                    prior = read_regular_at(backups_fd, self._backup_name(label))
                    if (
                        prior is None
                        or sha256_hex(prior) != plan.expected_previous_sha256
                    ):
                        raise GenerationMismatch("prior_backup_invalid", _LIMITED)
                self._restore(root_fd, plan, prior)
                unlink_at(backups_fd, self._backup_name(label))
        return ServiceReceipt(plan.lease, "rollback", _LIMITED, absent=True)
