"""Test-owned Darwin provisioning transaction over an injected launchd lifecycle."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Mapping, Sequence
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


def _read_regular(path: Path) -> bytes | None:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(st.st_mode):
        raise UnsafePath("plist_not_regular_file", _LIMITED)
    return path.read_bytes()


def ensure_private_subdir(root: Path, name: str, uid: int) -> Path:
    """Create or accept ``root/name`` only as an owned 0700 real directory."""
    path = root / name
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    except OSError:
        raise UnsafePath("subdir_unusable", _LIMITED) from None
    try:
        st = os.lstat(path)
    except OSError:
        raise UnsafePath("subdir_unusable", _LIMITED) from None
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != uid or st.st_mode & 0o077:
        raise UnsafePath("subdir_not_private", _LIMITED)
    return path


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


class DarwinProvisioner:
    """Plan, apply and roll back one test-owned plist inside a private root."""

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

    def _check_root(self, lease: ServiceLease) -> None:
        validate_test_label(lease.label)
        if lease.uid != self._uid:
            raise GenerationMismatch("uid_mismatch", _LIMITED)
        try:
            st = os.lstat(self._root)
        except OSError:
            raise UnsafePath("root_unusable", _LIMITED) from None
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != self._uid or st.st_mode & 0o077:
            raise UnsafePath("root_not_private", _LIMITED)
        if (st.st_dev, st.st_ino) != (lease.root_device, lease.root_inode):
            raise GenerationMismatch("root_identity_mismatch", _LIMITED)

    def _plist_path(self, label: str) -> Path:
        return self.plist_dir / f"{label}.plist"

    def _backup_path(self, label: str) -> Path:
        return self.backup_dir / f"{label}.prior"

    def plan(
        self,
        lease: ServiceLease,
        *,
        argv: Sequence[str],
        environment: Mapping[str, str],
        workdir: Path,
        role: str = DEFAULT_ROLE,
    ) -> ServicePlan:
        self._check_root(lease)
        path = self._plist_path(lease.label)
        data = render_plist(
            lease.label,
            argv=argv,
            environment=environment,
            workdir=workdir,
            runtime_dir=self._root,
            role=role,
        )
        prior = _read_regular(path)
        return ServicePlan(
            lease, data, path, None if prior is None else sha256_hex(prior)
        )

    def _revalidate(self, plan: ServicePlan) -> bytes | None:
        self._check_root(plan.lease)
        if plan.plist_path != self._plist_path(plan.lease.label):
            raise UnsafePath("plist_path_not_owned", _LIMITED)
        return _read_regular(plan.plist_path)

    def apply(self, plan: ServicePlan) -> ServiceReceipt:
        if self._lifecycle is None:
            raise CapabilityUnavailable("launchd_lifecycle_missing", _UNAVAILABLE)
        current = self._revalidate(plan)
        current_sha = None if current is None else sha256_hex(current)
        if current_sha != plan.expected_previous_sha256:
            raise GenerationMismatch("previous_digest_mismatch", _LIMITED)
        try:
            validate_plist_bytes(
                plan.plist_bytes, label=plan.lease.label, runtime_dir=self._root
            )
        except ValueError:
            raise UnsafePath("plist_scope_refused", _LIMITED) from None
        ensure_private_subdir(self._root, "backups", self._uid)
        if current is not None:
            _atomic_write(self._backup_path(plan.lease.label), current)
        _atomic_write(plan.plist_path, plan.plist_bytes)
        if _read_regular(plan.plist_path) != plan.plist_bytes:
            self._restore(plan, current)
            raise UnsafePath("plist_persist_mismatch", _LIMITED)
        label = plan.lease.label
        try:
            self._lifecycle.bootstrap(label, plan.plist_path)
        except BaseException as exc:
            self._after_failed_bootstrap(self._lifecycle, plan, current, exc)
            raise
        return ServiceReceipt(plan.lease, "apply", _LIMITED, absent=False)

    def _after_failed_bootstrap(
        self,
        lifecycle: LaunchdLifecycle,
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
            self._restore(plan, prior)
            self._backup_path(label).unlink(missing_ok=True)
            return
        raise ApplyUnknown("apply_partial_label_may_be_loaded", _UNKNOWN) from exc

    def _restore(self, plan: ServicePlan, prior: bytes | None) -> None:
        if prior is None:
            plan.plist_path.unlink(missing_ok=True)
        else:
            _atomic_write(plan.plist_path, prior)

    def rollback(self, plan: ServicePlan) -> ServiceReceipt:
        if self._lifecycle is None:
            raise CapabilityUnavailable("launchd_lifecycle_missing", _UNAVAILABLE)
        current = self._revalidate(plan)
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
        if current is not None and sha256_hex(current) != sha256_hex(plan.plist_bytes):
            # Foreign bytes: preserve them and do not unload someone else's job.
            raise GenerationMismatch("foreign_plist_preserved", _LIMITED)
        self._lifecycle.bootout(label)
        if not self._lifecycle.is_absent(label):
            # Keep the plist so a retry still owns and can finish the teardown.
            return ServiceReceipt(plan.lease, "rollback", _LIMITED, absent=False)
        prior: bytes | None = None
        if plan.expected_previous_sha256 is not None:
            ensure_private_subdir(self._root, "backups", self._uid)
            prior = _read_regular(self._backup_path(label))
            if prior is None or sha256_hex(prior) != plan.expected_previous_sha256:
                raise GenerationMismatch("prior_backup_invalid", _LIMITED)
        self._restore(plan, prior)
        self._backup_path(label).unlink(missing_ok=True)
        return ServiceReceipt(plan.lease, "rollback", _LIMITED, absent=True)
