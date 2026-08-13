"""Crash-safe publication primitives for protected Phase 9 runtime slots.

These primitives are intentionally not composed into the production broker yet.  A caller
must first retain the matching broker intent and, for selector changes, own the Phase 6
mutation fence.  This module only performs the exact filesystem transition it is given.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import secrets
import shutil
import stat
import threading
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Final

from binnacle.domain.privileged import canonical_sha256
from binnacle.domain.privileged_observation import RuntimeSlotState, VerifiedRuntimeSlot
from binnacle.privileged_broker.runtime_slots import (
    DEFAULT_RUNTIME_ROOT,
    RUNTIME_SLOT_MANIFEST,
    FilesystemRuntimeSlotInspector,
    RuntimeSlotInspectionSettings,
    RuntimeSlotManifest,
    RuntimeSlotVerificationError,
    canonical_runtime_slot_manifest_bytes,
)

_STAGING_DIRECTORY: Final = ".staging"
_SLOTS_DIRECTORY: Final = "slots"
_CURRENT_SELECTOR: Final = "current"
_RENAME_NOREPLACE: Final = 1
_COPY_BYTES: Final = 1_048_576
_SHA256_LENGTH: Final = 64


class RuntimeSlotPublicationError(RuntimeError):
    """A slot could not be proven, reserved, copied, or published."""


class RuntimeSlotPublicationUncertain(RuntimeSlotPublicationError):
    """A slot rename crossed but its durable postcondition is unproven."""


class RuntimeSelectorConflict(RuntimeSlotPublicationError):
    """The protected selector no longer has the request's exact preimage."""


class RuntimeSelectorPublicationUncertain(RuntimeSlotPublicationError):
    """A selector replacement crossed but its durable postcondition is unproven."""


@dataclass(frozen=True, slots=True)
class RuntimeSlotPublicationRequest:
    manifest: RuntimeSlotManifest
    expected_complete_manifest_sha256: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_sha256(self.expected_complete_manifest_sha256, "expected slot manifest")
        _require_aware(self.requested_at, "slot publication request")
        if self.manifest.role.value != "candidate" or self.manifest.state is not (
            RuntimeSlotState.COMPLETE
        ):
            raise RuntimeSlotPublicationError("only a complete candidate slot may be published")
        if self.manifest.complete_manifest_sha256 != self.expected_complete_manifest_sha256:
            raise RuntimeSlotPublicationError("slot publication manifest digest differs")
        if self.manifest.completed_at > self.requested_at:
            raise RuntimeSlotPublicationError("slot publication predates candidate completion")


@dataclass(frozen=True, slots=True)
class RuntimeSlotPublicationReceipt:
    slot_id: str
    slot_generation: int
    slot_identity_sha256: str
    complete_manifest_sha256: str
    candidate_verification_sha256: str
    source_root_identity_sha256: str
    byte_count: int
    inode_count: int
    already_published: bool
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_token(self.slot_id, "published runtime slot")
        if (
            self.slot_generation < 1
            or not 1 <= self.byte_count <= 100_000_000_000
            or not 1 <= self.inode_count <= 10_000_000
        ):
            raise RuntimeSlotPublicationError("slot publication receipt bounds are invalid")
        for value, name in (
            (self.slot_identity_sha256, "published slot identity"),
            (self.complete_manifest_sha256, "published complete manifest"),
            (self.candidate_verification_sha256, "published candidate verification"),
            (self.source_root_identity_sha256, "published source root"),
        ):
            _require_sha256(value, name)
        _require_aware(self.observed_at, "slot publication receipt")

    @property
    def receipt_sha256(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True, slots=True)
class RuntimeSelectorActivationRequest:
    selector_generation: int
    operation_id: str | None
    initial_bootstrap: bool
    expected_current_slot_id: str | None
    target_slot_id: str
    target_slot_identity_sha256: str
    retained_intent_sha256: str
    requested_at: datetime

    def __post_init__(self) -> None:
        if self.selector_generation < 1:
            raise RuntimeSlotPublicationError("runtime selector generation is invalid")
        if self.initial_bootstrap != (self.operation_id is None):
            raise RuntimeSlotPublicationError(
                "runtime selector operation identity is contradictory"
            )
        if self.initial_bootstrap and self.expected_current_slot_id is not None:
            raise RuntimeSlotPublicationError(
                "initial runtime selector publication unexpectedly has a preimage"
            )
        if self.operation_id is not None:
            _require_operation_id(self.operation_id, "runtime selector operation")
        if self.expected_current_slot_id is not None:
            _require_token(self.expected_current_slot_id, "expected runtime slot")
        _require_token(self.target_slot_id, "target runtime slot")
        _require_sha256(self.target_slot_identity_sha256, "target runtime slot")
        _require_sha256(self.retained_intent_sha256, "runtime selector intent")
        _require_aware(self.requested_at, "runtime selector request")
        expected_intent = runtime_selector_intent_sha256(
            selector_generation=self.selector_generation,
            operation_id=self.operation_id,
            initial_bootstrap=self.initial_bootstrap,
            expected_current_slot_id=self.expected_current_slot_id,
            target_slot_id=self.target_slot_id,
            target_slot_identity_sha256=self.target_slot_identity_sha256,
            requested_at=self.requested_at,
        )
        if self.retained_intent_sha256 != expected_intent:
            raise RuntimeSlotPublicationError("runtime selector retained intent differs")


@dataclass(frozen=True, slots=True)
class RuntimeSelectorActivationReceipt:
    selector_generation: int
    operation_id: str | None
    previous_slot_id: str | None
    selected_slot_id: str
    selected_slot_identity_sha256: str
    retained_intent_sha256: str
    selector_changed: bool
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.selector_generation < 1:
            raise RuntimeSlotPublicationError("runtime selector receipt generation is invalid")
        if self.operation_id is not None:
            _require_operation_id(self.operation_id, "runtime selector receipt operation")
        if self.previous_slot_id is not None:
            _require_token(self.previous_slot_id, "runtime selector previous slot")
        _require_token(self.selected_slot_id, "runtime selector selected slot")
        _require_sha256(self.selected_slot_identity_sha256, "runtime selector selected slot")
        _require_sha256(self.retained_intent_sha256, "runtime selector retained intent")
        _require_aware(self.observed_at, "runtime selector receipt")

    @property
    def receipt_sha256(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True, slots=True)
class RuntimeSlotPublicationSettings:
    export_root: Path
    expected_export_owner_uid: int
    expected_export_group_gid: int
    runtime_root: Path = DEFAULT_RUNTIME_ROOT
    expected_runtime_owner_uid: int = 0
    expected_runtime_group_gid: int = 0
    expected_staging_group_gid: int = 0
    maximum_slot_bytes: int = 100_000_000_000
    maximum_slot_inodes: int = 10_000_000
    maximum_retained_slots: int = 16
    require_fixed_runtime_root: bool = True

    def __post_init__(self) -> None:
        if self.require_fixed_runtime_root and self.runtime_root != DEFAULT_RUNTIME_ROOT:
            raise RuntimeSlotPublicationError("runtime publication root is not protected")
        if any(not _canonical_absolute(path) for path in (self.export_root, self.runtime_root)):
            raise RuntimeSlotPublicationError("runtime publication path is not canonical")
        if (
            self.export_root == self.runtime_root
            or self.runtime_root in self.export_root.parents
            or self.export_root in self.runtime_root.parents
        ):
            raise RuntimeSlotPublicationError("runtime export overlaps the protected runtime root")
        if (
            min(
                self.expected_export_owner_uid,
                self.expected_export_group_gid,
                self.expected_runtime_owner_uid,
                self.expected_runtime_group_gid,
                self.expected_staging_group_gid,
            )
            < 0
        ):
            raise RuntimeSlotPublicationError("runtime publication identity is invalid")
        if not 1_048_576 <= self.maximum_slot_bytes <= 100_000_000_000:
            raise RuntimeSlotPublicationError("runtime publication byte ceiling is invalid")
        if not 1_000 <= self.maximum_slot_inodes <= 10_000_000:
            raise RuntimeSlotPublicationError("runtime publication inode ceiling is invalid")
        if not 3 <= self.maximum_retained_slots <= 16:
            raise RuntimeSlotPublicationError("runtime retained-slot ceiling is invalid")


class FilesystemRuntimeSlotPublisher:
    """Copy a verified export and atomically publish/select only its exact generation."""

    def __init__(self, settings: RuntimeSlotPublicationSettings) -> None:
        self._settings = settings
        self._inspector = FilesystemRuntimeSlotInspector(
            RuntimeSlotInspectionSettings(
                runtime_root=settings.runtime_root,
                expected_owner_uid=settings.expected_runtime_owner_uid,
                expected_group_gid=settings.expected_runtime_group_gid,
                maximum_slot_bytes=settings.maximum_slot_bytes,
                maximum_slot_inodes=settings.maximum_slot_inodes,
                maximum_retained_slots=settings.maximum_retained_slots,
                require_fixed_root=settings.require_fixed_runtime_root,
            )
        )
        self._effect_lock = threading.Lock()

    def materialize_candidate(
        self,
        request: RuntimeSlotPublicationRequest,
    ) -> RuntimeSlotPublicationReceipt:
        with self._effect_lock:
            return self._materialize_candidate(request)

    def activate_complete_slot(
        self,
        request: RuntimeSelectorActivationRequest,
        *,
        observed_at: datetime,
    ) -> RuntimeSelectorActivationReceipt:
        _require_aware(observed_at, "runtime selector observation")
        if observed_at < request.requested_at:
            raise RuntimeSlotPublicationError("runtime selector observation predates its request")
        with self._effect_lock:
            return self._activate_complete_slot(request, observed_at=observed_at)

    def _materialize_candidate(
        self,
        request: RuntimeSlotPublicationRequest,
    ) -> RuntimeSlotPublicationReceipt:
        manifest = request.manifest
        self._verify_runtime_roots()
        source_metadata = self._verify_export_root()
        source_identity = canonical_sha256(
            {
                "device": source_metadata.st_dev,
                "group_gid": source_metadata.st_gid,
                "inode": source_metadata.st_ino,
                "manifest_sha256": manifest.complete_manifest_sha256,
                "owner_uid": source_metadata.st_uid,
            }
        )
        self._verify_export_tree(manifest)
        existing = self._existing_slot(manifest.slot_id)
        if existing is not None:
            self._require_same_published_slot(existing, manifest)
            return self._publication_receipt(
                existing,
                source_identity=source_identity,
                already_published=True,
                observed_at=request.requested_at,
            )
        self._require_unique_generation(manifest)
        self._reserve_capacity(manifest)

        staging_parent = self._settings.runtime_root / _STAGING_DIRECTORY
        stage_name = f"slot-{secrets.token_hex(16)}"
        stage_path = staging_parent / stage_name
        stage_descriptor: int | None = None
        published = False
        try:
            os.mkdir(stage_path, 0o700)
            os.chown(
                stage_path,
                self._settings.expected_runtime_owner_uid,
                self._settings.expected_runtime_group_gid,
            )
            self._copy_export(manifest, stage_path, expected_source=source_metadata)
            self._verify_export_tree(manifest)
            stage_descriptor = _open_directory(stage_path)
            self._rename_noreplace(
                source_parent=staging_parent,
                source_name=stage_name,
                target_parent=self._settings.runtime_root / _SLOTS_DIRECTORY,
                target_name=manifest.slot_id,
            )
            published = True
            os.fchmod(stage_descriptor, 0o550)
            os.fsync(stage_descriptor)
            _fsync_directory(staging_parent)
            _fsync_directory(self._settings.runtime_root / _SLOTS_DIRECTORY)
        except FileExistsError:
            existing = self._existing_slot(manifest.slot_id)
            if existing is None:
                raise RuntimeSlotPublicationError("runtime slot publication raced") from None
            self._require_same_published_slot(existing, manifest)
        except RuntimeSlotPublicationError:
            raise
        except OSError as exc:
            if published:
                raise RuntimeSlotPublicationUncertain(
                    "runtime slot publication durability is uncertain"
                ) from exc
            raise RuntimeSlotPublicationError("runtime slot publication failed") from exc
        finally:
            if stage_descriptor is not None:
                os.close(stage_descriptor)
            if not published and stage_path.exists():
                _remove_private_stage(stage_path)

        try:
            observed = self._inspector.inspect_sync(manifest.slot_id)
        except RuntimeSlotVerificationError as exc:
            error_type = (
                RuntimeSlotPublicationUncertain if published else RuntimeSlotPublicationError
            )
            raise error_type("published runtime slot failed exact verification") from exc
        try:
            self._require_same_published_slot(observed, manifest)
        except RuntimeSlotPublicationError as exc:
            if published:
                raise RuntimeSlotPublicationUncertain(
                    "published runtime slot identity is uncertain"
                ) from exc
            raise
        return self._publication_receipt(
            observed,
            source_identity=source_identity,
            already_published=not published,
            observed_at=request.requested_at,
        )

    def _activate_complete_slot(
        self,
        request: RuntimeSelectorActivationRequest,
        *,
        observed_at: datetime,
    ) -> RuntimeSelectorActivationReceipt:
        self._verify_runtime_roots()
        try:
            target = self._inspector.inspect_sync(request.target_slot_id)
            current = self._inspector.current_sync()
        except RuntimeSlotVerificationError as exc:
            raise RuntimeSelectorConflict("runtime selector precondition is unavailable") from exc
        if target.state not in {
            RuntimeSlotState.COMPLETE,
            RuntimeSlotState.ACTIVE,
            RuntimeSlotState.LKG,
        }:
            raise RuntimeSelectorConflict("runtime slot state cannot be selected")
        if target.slot_identity_sha256 != request.target_slot_identity_sha256:
            raise RuntimeSelectorConflict("runtime selector target identity changed")
        current_id = None if current is None else current.slot_id
        if current_id == request.target_slot_id:
            return self._selector_receipt(
                request,
                previous_slot_id=request.expected_current_slot_id,
                target=target,
                selector_changed=False,
                observed_at=observed_at,
            )
        if current_id != request.expected_current_slot_id:
            raise RuntimeSelectorConflict("runtime selector preimage changed")

        root = self._settings.runtime_root
        temporary_name = f".current-{secrets.token_hex(16)}"
        temporary = root / temporary_name
        replaced = False
        try:
            os.symlink(f"slots/{request.target_slot_id}", temporary)
            _fsync_directory(root)
            if request.expected_current_slot_id is None:
                self._rename_noreplace(
                    source_parent=root,
                    source_name=temporary_name,
                    target_parent=root,
                    target_name=_CURRENT_SELECTOR,
                )
            else:
                rechecked = self._inspector.current_sync()
                if rechecked is None or rechecked.slot_id != request.expected_current_slot_id:
                    raise RuntimeSelectorConflict("runtime selector preimage changed")
                root_fd = _open_directory(root)
                try:
                    os.replace(
                        temporary_name,
                        _CURRENT_SELECTOR,
                        src_dir_fd=root_fd,
                        dst_dir_fd=root_fd,
                    )
                finally:
                    os.close(root_fd)
            replaced = True
            _fsync_directory(root)
            selected = self._inspector.current_sync()
            if (
                selected is None
                or selected.slot_id != request.target_slot_id
                or selected.slot_identity_sha256 != request.target_slot_identity_sha256
            ):
                raise RuntimeSelectorPublicationUncertain(
                    "runtime selector postcondition is unproven"
                )
        except RuntimeSelectorConflict:
            raise
        except RuntimeSelectorPublicationUncertain:
            raise
        except FileExistsError as exc:
            raise RuntimeSelectorConflict("runtime selector preimage changed") from exc
        except RuntimeSlotVerificationError as exc:
            if replaced:
                raise RuntimeSelectorPublicationUncertain(
                    "runtime selector postcondition is unavailable"
                ) from exc
            raise RuntimeSelectorConflict("runtime selector precondition is unavailable") from exc
        except OSError as exc:
            if replaced:
                raise RuntimeSelectorPublicationUncertain(
                    "runtime selector durability is uncertain"
                ) from exc
            raise RuntimeSlotPublicationError("runtime selector was not published") from exc
        finally:
            if not replaced:
                with suppress(OSError):
                    temporary.unlink()
        return self._selector_receipt(
            request,
            previous_slot_id=current_id,
            target=target,
            selector_changed=True,
            observed_at=observed_at,
        )

    def _verify_runtime_roots(self) -> None:
        root = self._settings.runtime_root
        slots = root / _SLOTS_DIRECTORY
        staging = root / _STAGING_DIRECTORY
        expected = (
            self._settings.expected_runtime_owner_uid,
            self._settings.expected_runtime_group_gid,
            0o750,
        )
        root_metadata = _require_directory(root, expected, "runtime root")
        slots_metadata = _require_directory(slots, expected, "runtime slots root")
        staging_metadata = _require_directory(
            staging,
            (
                self._settings.expected_runtime_owner_uid,
                self._settings.expected_staging_group_gid,
                0o700,
            ),
            "runtime staging root",
        )
        if len({root_metadata.st_dev, slots_metadata.st_dev, staging_metadata.st_dev}) != 1:
            raise RuntimeSlotPublicationError("runtime slot roots are not on one filesystem")

    def _verify_export_root(self) -> os.stat_result:
        return _require_directory(
            self._settings.export_root,
            (
                self._settings.expected_export_owner_uid,
                self._settings.expected_export_group_gid,
                0o550,
            ),
            "runtime export root",
        )

    def _verify_export_tree(self, manifest: RuntimeSlotManifest) -> None:
        directories: list[str] = []
        files: list[str] = []
        pending = [(self._settings.export_root, PurePosixPath())]
        seen = 0
        while pending:
            directory, relative_parent = pending.pop()
            try:
                iterator = os.scandir(directory)
            except OSError as exc:
                raise RuntimeSlotPublicationError("runtime export tree is unavailable") from exc
            with iterator:
                for entry in iterator:
                    seen += 1
                    if seen > self._settings.maximum_slot_inodes:
                        raise RuntimeSlotPublicationError("runtime export inode ceiling exceeded")
                    relative = relative_parent / entry.name
                    relative_text = relative.as_posix()
                    try:
                        metadata = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        raise RuntimeSlotPublicationError(
                            "runtime export entry is unavailable"
                        ) from exc
                    if stat.S_ISLNK(metadata.st_mode):
                        raise RuntimeSlotPublicationError("runtime export contains a symlink")
                    if stat.S_ISDIR(metadata.st_mode):
                        if _identity_mode(metadata) != (
                            self._settings.expected_export_owner_uid,
                            self._settings.expected_export_group_gid,
                            0o550,
                        ):
                            raise RuntimeSlotPublicationError(
                                "runtime export directory identity differs"
                            )
                        directories.append(relative_text)
                        pending.append((Path(entry.path), relative))
                    elif stat.S_ISREG(metadata.st_mode):
                        files.append(relative_text)
                    else:
                        raise RuntimeSlotPublicationError(
                            "runtime export entry type is unsupported"
                        )
        if tuple(sorted(directories)) != manifest.directories or tuple(sorted(files)) != tuple(
            item.path for item in manifest.files
        ):
            raise RuntimeSlotPublicationError("runtime export tree differs from its manifest")

    def _copy_export(
        self,
        manifest: RuntimeSlotManifest,
        stage_path: Path,
        *,
        expected_source: os.stat_result,
    ) -> None:
        stage_fd = _open_directory(stage_path)
        source_fd = _open_directory(self._settings.export_root)
        try:
            opened_source = os.fstat(source_fd)
            if (
                opened_source.st_dev,
                opened_source.st_ino,
                *_identity_mode(opened_source),
            ) != (
                expected_source.st_dev,
                expected_source.st_ino,
                self._settings.expected_export_owner_uid,
                self._settings.expected_export_group_gid,
                0o550,
            ):
                raise RuntimeSlotPublicationError("runtime export root identity changed")
            for relative in manifest.directories:
                os.mkdir(relative, 0o700, dir_fd=stage_fd)
            for expected in manifest.files:
                self._copy_one_file(
                    source_fd=source_fd,
                    stage_fd=stage_fd,
                    expected_path=expected.path,
                    expected_mode=int(expected.mode, 8),
                    expected_size=expected.byte_count,
                    expected_sha256=expected.sha256,
                )
            manifest_bytes = canonical_runtime_slot_manifest_bytes(manifest)
            self._write_destination(
                stage_fd=stage_fd,
                relative_path=RUNTIME_SLOT_MANIFEST,
                mode=0o440,
                expected_size=len(manifest_bytes),
                content=manifest_bytes,
            )
            for relative in sorted(
                manifest.directories,
                key=lambda value: (len(PurePosixPath(value).parts), value),
                reverse=True,
            ):
                descriptor = os.open(
                    relative,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=stage_fd,
                )
                try:
                    os.fchown(
                        descriptor,
                        self._settings.expected_runtime_owner_uid,
                        self._settings.expected_runtime_group_gid,
                    )
                    os.fchmod(descriptor, 0o550)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            os.fchown(
                stage_fd,
                self._settings.expected_runtime_owner_uid,
                self._settings.expected_runtime_group_gid,
            )
            # The private staging root remains owner-writable until rename.  Linux may
            # reject moving a sealed directory for an unprivileged owner; the held
            # descriptor is sealed and fsynced immediately after the atomic publish.
            os.fchmod(stage_fd, 0o700)
            os.fsync(stage_fd)
        except OSError as exc:
            raise RuntimeSlotPublicationError("runtime export copy failed") from exc
        finally:
            os.close(source_fd)
            os.close(stage_fd)

    def _copy_one_file(
        self,
        *,
        source_fd: int,
        stage_fd: int,
        expected_path: str,
        expected_mode: int,
        expected_size: int,
        expected_sha256: str,
    ) -> None:
        source = _open_relative_file(source_fd, expected_path)
        try:
            metadata = os.fstat(source)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or _identity_mode(metadata)
                != (
                    self._settings.expected_export_owner_uid,
                    self._settings.expected_export_group_gid,
                    expected_mode,
                )
                or metadata.st_size != expected_size
            ):
                raise RuntimeSlotPublicationError("runtime export file identity differs")
            destination = os.open(
                expected_path,
                os.O_CREAT
                | os.O_EXCL
                | os.O_WRONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=stage_fd,
            )
            try:
                if expected_size:
                    os.posix_fallocate(destination, 0, expected_size)
                digest = hashlib.sha256()
                copied = 0
                while chunk := os.read(source, _COPY_BYTES):
                    copied += len(chunk)
                    if copied > expected_size:
                        raise RuntimeSlotPublicationError(
                            "runtime export file grew during publication"
                        )
                    _write_all(destination, chunk)
                    digest.update(chunk)
                if copied != expected_size or digest.hexdigest() != expected_sha256:
                    raise RuntimeSlotPublicationError("runtime export file digest differs")
                os.fchown(
                    destination,
                    self._settings.expected_runtime_owner_uid,
                    self._settings.expected_runtime_group_gid,
                )
                os.fchmod(destination, expected_mode)
                os.fsync(destination)
            finally:
                os.close(destination)
        finally:
            os.close(source)

    def _write_destination(
        self,
        *,
        stage_fd: int,
        relative_path: str,
        mode: int,
        expected_size: int,
        content: bytes,
    ) -> None:
        descriptor = os.open(
            relative_path,
            os.O_CREAT
            | os.O_EXCL
            | os.O_WRONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=stage_fd,
        )
        try:
            if expected_size:
                os.posix_fallocate(descriptor, 0, expected_size)
            _write_all(descriptor, content)
            os.fchown(
                descriptor,
                self._settings.expected_runtime_owner_uid,
                self._settings.expected_runtime_group_gid,
            )
            os.fchmod(descriptor, mode)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _reserve_capacity(self, manifest: RuntimeSlotManifest) -> None:
        manifest_bytes = len(canonical_runtime_slot_manifest_bytes(manifest))
        required_bytes = manifest.byte_count + manifest_bytes
        required_inodes = manifest.inode_count + 2
        if (
            required_bytes > self._settings.maximum_slot_bytes
            or required_inodes > self._settings.maximum_slot_inodes
        ):
            raise RuntimeSlotPublicationError("runtime slot exceeds configured capacity")
        try:
            available = os.statvfs(self._settings.runtime_root / _STAGING_DIRECTORY)
        except OSError as exc:
            raise RuntimeSlotPublicationError("runtime slot capacity is unavailable") from exc
        if available.f_bavail * available.f_frsize < required_bytes or (
            available.f_favail != 0 and available.f_favail < required_inodes
        ):
            raise RuntimeSlotPublicationError("runtime slot capacity reservation failed")

    def _existing_slot(self, slot_id: str) -> VerifiedRuntimeSlot | None:
        path = self._settings.runtime_root / _SLOTS_DIRECTORY / slot_id
        try:
            path.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise RuntimeSlotPublicationError("runtime slot identity is unavailable") from exc
        try:
            return self._inspector.inspect_sync(slot_id)
        except RuntimeSlotVerificationError as exc:
            raise RuntimeSlotPublicationError("existing runtime slot is not exact") from exc

    def _require_unique_generation(self, manifest: RuntimeSlotManifest) -> None:
        slots = self._settings.runtime_root / _SLOTS_DIRECTORY
        count = 0
        try:
            iterator = os.scandir(slots)
        except OSError as exc:
            raise RuntimeSlotPublicationError("runtime slot inventory is unavailable") from exc
        with iterator:
            for entry in iterator:
                count += 1
                if count >= self._settings.maximum_retained_slots:
                    raise RuntimeSlotPublicationError("runtime retained-slot ceiling reached")
                try:
                    existing = self._inspector.inspect_sync(entry.name)
                except RuntimeSlotVerificationError as exc:
                    raise RuntimeSlotPublicationError("retained runtime slot is unsafe") from exc
                if existing.slot_generation == manifest.slot_generation:
                    raise RuntimeSlotPublicationError("runtime slot generation is already used")

    @staticmethod
    def _require_same_published_slot(
        observed: VerifiedRuntimeSlot,
        manifest: RuntimeSlotManifest,
    ) -> None:
        if (
            observed.complete_manifest_sha256 != manifest.complete_manifest_sha256
            or observed.candidate_verification_sha256 != manifest.candidate_verification_sha256
            or observed.slot_generation != manifest.slot_generation
        ):
            raise RuntimeSlotPublicationError("published runtime slot conflicts with request")

    @staticmethod
    def _publication_receipt(
        observed: VerifiedRuntimeSlot,
        *,
        source_identity: str,
        already_published: bool,
        observed_at: datetime,
    ) -> RuntimeSlotPublicationReceipt:
        return RuntimeSlotPublicationReceipt(
            slot_id=observed.slot_id,
            slot_generation=observed.slot_generation,
            slot_identity_sha256=observed.slot_identity_sha256,
            complete_manifest_sha256=observed.complete_manifest_sha256,
            candidate_verification_sha256=observed.candidate_verification_sha256,
            source_root_identity_sha256=source_identity,
            byte_count=observed.byte_count,
            inode_count=observed.inode_count,
            already_published=already_published,
            observed_at=observed_at,
        )

    @staticmethod
    def _selector_receipt(
        request: RuntimeSelectorActivationRequest,
        *,
        previous_slot_id: str | None,
        target: VerifiedRuntimeSlot,
        selector_changed: bool,
        observed_at: datetime,
    ) -> RuntimeSelectorActivationReceipt:
        return RuntimeSelectorActivationReceipt(
            selector_generation=request.selector_generation,
            operation_id=request.operation_id,
            previous_slot_id=previous_slot_id,
            selected_slot_id=target.slot_id,
            selected_slot_identity_sha256=target.slot_identity_sha256,
            retained_intent_sha256=request.retained_intent_sha256,
            selector_changed=selector_changed,
            observed_at=observed_at,
        )

    @staticmethod
    def _rename_noreplace(
        *,
        source_parent: Path,
        source_name: str,
        target_parent: Path,
        target_name: str,
    ) -> None:
        source_fd = _open_directory(source_parent)
        target_fd = _open_directory(target_parent)
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            try:
                renameat2 = libc.renameat2
            except AttributeError as exc:
                raise RuntimeSlotPublicationError(
                    "atomic no-replace publication is unavailable"
                ) from exc
            renameat2.argtypes = (
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            )
            renameat2.restype = ctypes.c_int
            result = renameat2(
                source_fd,
                os.fsencode(source_name),
                target_fd,
                os.fsencode(target_name),
                _RENAME_NOREPLACE,
            )
            if result != 0:
                error = ctypes.get_errno()
                if error == errno.EEXIST:
                    raise FileExistsError(error, os.strerror(error), target_name)
                raise OSError(error, os.strerror(error), source_name)
        finally:
            os.close(target_fd)
            os.close(source_fd)


def runtime_selector_intent_sha256(
    *,
    selector_generation: int,
    operation_id: str | None,
    initial_bootstrap: bool,
    expected_current_slot_id: str | None,
    target_slot_id: str,
    target_slot_identity_sha256: str,
    requested_at: datetime,
) -> str:
    """Return the exact intent digest that must be retained before selector mutation."""

    return canonical_sha256(
        {
            "expected_current_slot_id": expected_current_slot_id,
            "initial_bootstrap": initial_bootstrap,
            "operation_id": operation_id,
            "requested_at": requested_at,
            "selector_generation": selector_generation,
            "target_slot_id": target_slot_id,
            "target_slot_identity_sha256": target_slot_identity_sha256,
        }
    )


def _open_relative_file(root_fd: int, relative_path: str) -> int:
    parts = PurePosixPath(relative_path).parts
    parent = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            child = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent,
            )
            os.close(parent)
            parent = child
        return os.open(
            parts[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent,
        )
    finally:
        os.close(parent)


def _require_directory(
    path: Path,
    expected_identity: tuple[int, int, int],
    name: str,
) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RuntimeSlotPublicationError(f"{name} is unavailable") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or _identity_mode(metadata) != expected_identity
    ):
        raise RuntimeSlotPublicationError(f"{name} identity is unsafe")
    return metadata


def _open_directory(path: Path) -> int:
    return os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )


def _fsync_directory(path: Path) -> None:
    descriptor = _open_directory(path)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, content: bytes) -> None:
    view = memoryview(content)
    written = 0
    while written < len(view):
        count = os.write(descriptor, view[written:])
        if count <= 0:
            raise OSError("runtime slot write made no progress")
        written += count


def _remove_private_stage(path: Path) -> None:
    for root, directories, _files in os.walk(path, topdown=False, followlinks=False):
        for directory in directories:
            with suppress(OSError):
                os.chmod(Path(root) / directory, 0o700, follow_symlinks=False)
    with suppress(OSError):
        path.chmod(0o700)
    try:
        shutil.rmtree(path)
    except OSError as exc:
        raise RuntimeSlotPublicationError("private runtime staging cleanup failed") from exc


def _canonical_absolute(path: Path) -> bool:
    return path.is_absolute() and path == Path(os.path.normpath(str(path)))


def _identity_mode(metadata: os.stat_result) -> tuple[int, int, int]:
    return metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)


def _require_sha256(value: str, name: str) -> None:
    if len(value) != _SHA256_LENGTH or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise RuntimeSlotPublicationError(f"{name} digest is invalid")


def _require_token(value: str, name: str) -> None:
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise RuntimeSlotPublicationError(f"{name} identity is invalid") from exc
    if (
        not 1 <= len(encoded) <= 160
        or not value[0].isalnum()
        or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for character in value)
        or ".." in value
    ):
        raise RuntimeSlotPublicationError(f"{name} identity is invalid")


def _require_operation_id(value: str, name: str) -> None:
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise RuntimeSlotPublicationError(f"{name} identity is invalid") from exc
    if (
        not 1 <= len(encoded) <= 160
        or not value[0].isalnum()
        or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
            for character in value
        )
        or ".." in value
    ):
        raise RuntimeSlotPublicationError(f"{name} identity is invalid")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeSlotPublicationError(f"{name} time is not timezone-aware")


__all__ = [
    "FilesystemRuntimeSlotPublisher",
    "RuntimeSelectorActivationReceipt",
    "RuntimeSelectorActivationRequest",
    "RuntimeSelectorConflict",
    "RuntimeSelectorPublicationUncertain",
    "RuntimeSlotPublicationError",
    "RuntimeSlotPublicationReceipt",
    "RuntimeSlotPublicationRequest",
    "RuntimeSlotPublicationSettings",
    "RuntimeSlotPublicationUncertain",
    "runtime_selector_intent_sha256",
]
