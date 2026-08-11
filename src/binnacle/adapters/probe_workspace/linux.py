"""Descriptor-relative, no-overwrite filesystem effects for the Phase 5 probe."""

from __future__ import annotations

import asyncio
import ctypes
import os
import secrets
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from binnacle.domain.probe_workspace import (
    MAX_PROBE_FILE_BYTES,
    ProbeFileObservation,
    ProbeRootIdentity,
    ProbeTargetState,
    canonical_sha256,
    content_sha256,
    normalize_probe_path,
    validate_probe_identifier,
    validate_sha256,
)


class ProbeWorkspaceFilesystemError(RuntimeError):
    """The protected root or an effect result cannot be verified safely."""


class ProbeEffectNotStarted(ProbeWorkspaceFilesystemError):
    """A verified pre-effect condition prevented the boundary from being crossed."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class _DirectoryIdentity:
    device: int
    inode: int
    owner_uid: int
    owner_gid: int
    mode: int


class LinuxProbeWorkspace:
    """Own exactly one fixed private root and two bounded filesystem effects."""

    def __init__(self, *, root: Path, maximum_file_bytes: int = MAX_PROBE_FILE_BYTES) -> None:
        if not root.is_absolute():
            raise ValueError("probe workspace root must be absolute")
        if maximum_file_bytes < 1 or maximum_file_bytes > MAX_PROBE_FILE_BYTES:
            raise ValueError("probe workspace byte limit is outside the frozen bound")
        self._root = root
        self._staging = root / ".staging"
        self._maximum_file_bytes = maximum_file_bytes
        self._root_identity: ProbeRootIdentity | None = None
        self._staging_identity: _DirectoryIdentity | None = None

    @property
    def root(self) -> Path:
        return self._root

    async def initialize(self) -> None:
        root, staging = await asyncio.to_thread(self._verify_layout)
        self._root_identity = root
        self._staging_identity = staging

    async def root_identity(self) -> ProbeRootIdentity:
        observed, staging = await asyncio.to_thread(self._verify_layout)
        if (
            self._root_identity is not None
            and observed.digest_sha256 != self._root_identity.digest_sha256
        ):
            raise ProbeWorkspaceFilesystemError("probe root identity changed")
        if self._staging_identity is not None and staging != self._staging_identity:
            raise ProbeWorkspaceFilesystemError("probe staging identity changed")
        self._root_identity = observed
        self._staging_identity = staging
        return observed

    async def observe(self, relative_path: str) -> ProbeFileObservation:
        name = normalize_probe_path(relative_path)
        return await asyncio.to_thread(self._observe, name)

    async def create(
        self,
        *,
        operation_id: str,
        artifact_id: str,
        path_generation: int,
        relative_path: str,
        content: bytes,
        expected_content_sha256: str,
    ) -> str:
        return await asyncio.to_thread(
            self._create,
            operation_id,
            artifact_id,
            path_generation,
            normalize_probe_path(relative_path),
            content,
            validate_sha256(expected_content_sha256, name="content_sha256"),
        )

    async def remove(
        self,
        *,
        operation_id: str,
        artifact_id: str,
        path_generation: int,
        relative_path: str,
        expected_content_sha256: str,
        expected_file_identity_digest: str,
    ) -> str | None:
        return await asyncio.to_thread(
            self._remove,
            operation_id,
            artifact_id,
            path_generation,
            normalize_probe_path(relative_path),
            validate_sha256(expected_content_sha256, name="content_sha256"),
            validate_sha256(expected_file_identity_digest, name="file_identity_digest"),
        )

    def _verify_layout(self) -> tuple[ProbeRootIdentity, _DirectoryIdentity]:
        try:
            root_path = self._root.lstat()
            staging_path = self._staging.lstat()
            flags = (
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            root_fd = os.open(self._root, flags)
            try:
                root = os.fstat(root_fd)
                staging_fd = os.open(".staging", flags, dir_fd=root_fd)
                try:
                    staging = os.fstat(staging_fd)
                finally:
                    os.close(staging_fd)
            finally:
                os.close(root_fd)
        except OSError as exc:
            raise ProbeWorkspaceFilesystemError(
                "probe root or staging directory cannot be opened safely"
            ) from exc
        for path_info, descriptor_info in ((root_path, root), (staging_path, staging)):
            if (
                stat.S_ISLNK(path_info.st_mode)
                or not stat.S_ISDIR(path_info.st_mode)
                or path_info.st_dev != descriptor_info.st_dev
                or path_info.st_ino != descriptor_info.st_ino
                or descriptor_info.st_uid != os.geteuid()
                or descriptor_info.st_gid != os.getegid()
                or stat.S_IMODE(descriptor_info.st_mode) != 0o700
            ):
                raise ProbeWorkspaceFilesystemError(
                    "probe root or staging ownership/type/mode is unsafe"
                )
        if root.st_dev != staging.st_dev or root.st_ino == staging.st_ino:
            raise ProbeWorkspaceFilesystemError(
                "probe root and staging must be distinct on one filesystem"
            )
        root_identity = self._directory_identity(root)
        staging_identity = self._directory_identity(staging)
        digest = canonical_sha256(
            {
                "device": root_identity.device,
                "inode": root_identity.inode,
                "mode": root_identity.mode,
                "owner_gid": root_identity.owner_gid,
                "owner_uid": root_identity.owner_uid,
            }
        )
        return (
            ProbeRootIdentity(
                digest_sha256=digest,
                device=root_identity.device,
                inode=root_identity.inode,
                owner_uid=root_identity.owner_uid,
                owner_gid=root_identity.owner_gid,
                mode=root_identity.mode,
            ),
            staging_identity,
        )

    def _open_directories(self) -> tuple[int, int]:
        if self._root_identity is None or self._staging_identity is None:
            raise ProbeWorkspaceFilesystemError("probe workspace is not initialized")
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        root_fd = os.open(self._root, flags)
        staging_fd: int | None = None
        try:
            staging_fd = os.open(".staging", flags, dir_fd=root_fd)
            root = os.fstat(root_fd)
            staging = os.fstat(staging_fd)
            root_identity = self._directory_identity(root)
            staging_identity = self._directory_identity(staging)
            expected_root = self._root_identity
            if (
                root_identity.device != expected_root.device
                or root_identity.inode != expected_root.inode
                or root_identity.owner_uid != expected_root.owner_uid
                or root_identity.owner_gid != expected_root.owner_gid
                or root_identity.mode != expected_root.mode
                or staging_identity != self._staging_identity
                or root_identity.device != staging_identity.device
                or root_identity.inode == staging_identity.inode
            ):
                raise ProbeWorkspaceFilesystemError(
                    "probe root or staging identity changed before effect"
                )
        except Exception:
            if staging_fd is not None:
                os.close(staging_fd)
            os.close(root_fd)
            raise
        return root_fd, staging_fd

    @staticmethod
    def _directory_identity(info: os.stat_result) -> _DirectoryIdentity:
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_gid != os.getegid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise ProbeWorkspaceFilesystemError(
                "probe root or staging ownership/type/mode is unsafe"
            )
        return _DirectoryIdentity(
            device=info.st_dev,
            inode=info.st_ino,
            owner_uid=info.st_uid,
            owner_gid=info.st_gid,
            mode=stat.S_IMODE(info.st_mode),
        )

    def _observe(self, relative_path: str) -> ProbeFileObservation:
        root_fd, staging_fd = self._open_directories()
        os.close(staging_fd)
        try:
            return self._observe_at(root_fd, relative_path)
        finally:
            os.close(root_fd)

    def _observe_at(self, root_fd: int, relative_path: str) -> ProbeFileObservation:
        try:
            path_info = os.stat(relative_path, dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            return ProbeFileObservation(ProbeTargetState.ABSENT)
        if not stat.S_ISREG(path_info.st_mode) or stat.S_ISLNK(path_info.st_mode):
            return ProbeFileObservation(ProbeTargetState.MISMATCH)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(relative_path, flags, dir_fd=root_fd)
        except OSError:
            return ProbeFileObservation(ProbeTargetState.MISMATCH)
        try:
            info = os.fstat(descriptor)
            if (
                info.st_dev != path_info.st_dev
                or info.st_ino != path_info.st_ino
                or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_gid != os.getegid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or not 0 <= info.st_size <= self._maximum_file_bytes
            ):
                return ProbeFileObservation(ProbeTargetState.MISMATCH)
            content = self._read_bounded(descriptor)
            digest = content_sha256(content)
            identity = self._file_identity(info, digest)
            return ProbeFileObservation(
                ProbeTargetState.EXACT,
                file_identity_digest=identity,
                content_sha256=digest,
                byte_count=len(content),
            )
        finally:
            os.close(descriptor)

    def _create(
        self,
        operation_id: str,
        artifact_id: str,
        path_generation: int,
        relative_path: str,
        content: bytes,
        expected_content_sha256: str,
    ) -> str:
        validate_probe_identifier(operation_id, name="operation_id")
        validate_probe_identifier(artifact_id, name="artifact_id")
        if path_generation < 1 or len(content) > self._maximum_file_bytes:
            raise ProbeEffectNotStarted("probe_write_bounds_invalid")
        if content_sha256(content) != expected_content_sha256:
            raise ProbeEffectNotStarted("probe_write_content_digest_mismatch")
        root_fd, staging_fd = self._open_directories()
        staging_name = f".binnacle-{artifact_id}-{secrets.token_hex(12)}"
        staging_descriptor: int | None = None
        published = False
        try:
            if self._observe_at(root_fd, relative_path).state is not ProbeTargetState.ABSENT:
                raise ProbeEffectNotStarted("probe_target_not_absent")
            flags = (
                os.O_CREAT
                | os.O_EXCL
                | os.O_RDWR
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            staging_descriptor = os.open(staging_name, flags, 0o600, dir_fd=staging_fd)
            self._write_all(staging_descriptor, content)
            os.fsync(staging_descriptor)
            os.lseek(staging_descriptor, 0, os.SEEK_SET)
            if content_sha256(self._read_bounded(staging_descriptor)) != expected_content_sha256:
                raise ProbeEffectNotStarted("probe_staging_verification_failed")
            try:
                os.link(
                    staging_name,
                    relative_path,
                    src_dir_fd=staging_fd,
                    dst_dir_fd=root_fd,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise ProbeEffectNotStarted("probe_target_not_absent") from exc
            published = True
            os.fsync(root_fd)
            observation = self._observe_at(root_fd, relative_path)
            if (
                observation.state is not ProbeTargetState.EXACT
                or observation.content_sha256 != expected_content_sha256
                or observation.byte_count != len(content)
                or observation.file_identity_digest is None
            ):
                raise ProbeWorkspaceFilesystemError("published probe file cannot be verified")
            os.unlink(staging_name, dir_fd=staging_fd)
            os.fsync(staging_fd)
            return (
                f"probe-write:v1:{artifact_id}:{path_generation}:{observation.file_identity_digest}"
            )
        except ProbeEffectNotStarted:
            raise
        except Exception as exc:
            if published:
                raise
            raise ProbeEffectNotStarted("probe_write_not_started") from exc
        finally:
            if staging_descriptor is not None:
                os.close(staging_descriptor)
            with suppress(FileNotFoundError, OSError):
                os.unlink(staging_name, dir_fd=staging_fd)
                os.fsync(staging_fd)
            os.close(staging_fd)
            os.close(root_fd)

    def _remove(
        self,
        operation_id: str,
        artifact_id: str,
        path_generation: int,
        relative_path: str,
        expected_content_sha256: str,
        expected_file_identity_digest: str,
    ) -> str | None:
        validate_probe_identifier(operation_id, name="operation_id")
        validate_probe_identifier(artifact_id, name="artifact_id")
        if path_generation < 1:
            raise ProbeEffectNotStarted("probe_cleanup_generation_invalid")
        root_fd, staging_fd = self._open_directories()
        quarantine_correlation = canonical_sha256(
            {
                "artifact_id": artifact_id,
                "operation_id": operation_id,
                "path_generation": path_generation,
            }
        )[:32]
        quarantine_name = (
            f".binnacle-cleanup-tomb-v1-{quarantine_correlation}-{secrets.token_hex(12)}"
        )
        quarantined = False
        quarantine_descriptor: int | None = None
        try:
            observation = self._observe_at(root_fd, relative_path)
            if observation.state is ProbeTargetState.ABSENT:
                return None
            if (
                observation.state is not ProbeTargetState.EXACT
                or observation.content_sha256 != expected_content_sha256
                or observation.file_identity_digest != expected_file_identity_digest
            ):
                raise ProbeEffectNotStarted("probe_cleanup_identity_mismatch")
            try:
                self._rename_noreplace(
                    source_dir_fd=root_fd,
                    source_name=relative_path,
                    destination_dir_fd=staging_fd,
                    destination_name=quarantine_name,
                )
            except FileNotFoundError:
                return None
            except FileExistsError as exc:
                raise ProbeEffectNotStarted("probe_cleanup_quarantine_collision") from exc
            quarantined = True
            quarantine_descriptor = os.open(
                quarantine_name,
                os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=staging_fd,
            )
            quarantined_observation = self._observe_descriptor(quarantine_descriptor)
            if (
                quarantined_observation.state is not ProbeTargetState.EXACT
                or quarantined_observation.content_sha256 != expected_content_sha256
                or quarantined_observation.file_identity_digest != expected_file_identity_digest
            ):
                os.close(quarantine_descriptor)
                quarantine_descriptor = None
                try:
                    self._rename_noreplace(
                        source_dir_fd=staging_fd,
                        source_name=quarantine_name,
                        destination_dir_fd=root_fd,
                        destination_name=relative_path,
                    )
                    os.fsync(staging_fd)
                    os.fsync(root_fd)
                except Exception as exc:
                    raise ProbeWorkspaceFilesystemError(
                        "mismatched cleanup quarantine could not be restored"
                    ) from exc
                quarantined = False
                raise ProbeEffectNotStarted("probe_cleanup_identity_changed")

            # Linux has no unlink-by-open-fd. A pathname unlink here would recreate
            # the same substitution race inside .staging. Destroy only the verified
            # held inode and retain its empty private tomb until separately reviewed
            # maintenance can account for it.
            os.ftruncate(quarantine_descriptor, 0)
            os.fsync(quarantine_descriptor)
            os.fsync(staging_fd)
            os.fsync(root_fd)
            if self._observe_at(root_fd, relative_path).state is not ProbeTargetState.ABSENT:
                raise ProbeWorkspaceFilesystemError(
                    "probe cleanup target was replaced after quarantine"
                )
            return (
                f"probe-cleanup:v1:{artifact_id}:{path_generation}:{expected_file_identity_digest}"
            )
        except ProbeEffectNotStarted:
            raise
        except FileNotFoundError:
            if quarantined:
                raise
            return None
        except Exception as exc:
            if quarantined:
                raise
            raise ProbeEffectNotStarted("probe_cleanup_not_started") from exc
        finally:
            if quarantine_descriptor is not None:
                os.close(quarantine_descriptor)
            os.close(staging_fd)
            os.close(root_fd)

    @staticmethod
    def _rename_noreplace(
        *,
        source_dir_fd: int,
        source_name: str,
        destination_dir_fd: int,
        destination_name: str,
    ) -> None:
        """Atomically rename one directory entry without replacing another."""

        libc = ctypes.CDLL(None, use_errno=True)
        try:
            renameat2 = libc.renameat2
        except AttributeError as exc:
            raise ProbeWorkspaceFilesystemError(
                "renameat2 no-replace is unavailable for probe cleanup"
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
            source_dir_fd,
            os.fsencode(source_name),
            destination_dir_fd,
            os.fsencode(destination_name),
            1,  # RENAME_NOREPLACE
        )
        if result != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), source_name)

    def _observe_descriptor(self, descriptor: int) -> ProbeFileObservation:
        """Verify an already-open inode without any second pathname lookup."""

        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_gid != os.getegid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or not 0 <= info.st_size <= self._maximum_file_bytes
        ):
            return ProbeFileObservation(ProbeTargetState.MISMATCH)
        os.lseek(descriptor, 0, os.SEEK_SET)
        content = self._read_bounded(descriptor)
        digest = content_sha256(content)
        return ProbeFileObservation(
            ProbeTargetState.EXACT,
            file_identity_digest=self._file_identity(info, digest),
            content_sha256=digest,
            byte_count=len(content),
        )

    def _read_bounded(self, descriptor: int) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65_536, self._maximum_file_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > self._maximum_file_bytes:
                raise ProbeWorkspaceFilesystemError("probe file exceeds its structural bound")
        return b"".join(chunks)

    @staticmethod
    def _write_all(descriptor: int, content: bytes) -> None:
        view = memoryview(content)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise OSError("short probe staging write")
            written += count

    @staticmethod
    def _file_identity(info: os.stat_result, digest: str) -> str:
        return canonical_sha256(
            {
                "content_sha256": digest,
                "device": info.st_dev,
                "gid": info.st_gid,
                "inode": info.st_ino,
                "mode": stat.S_IMODE(info.st_mode),
                "size": info.st_size,
                "uid": info.st_uid,
            }
        )


__all__ = [
    "LinuxProbeWorkspace",
    "ProbeEffectNotStarted",
    "ProbeWorkspaceFilesystemError",
]
