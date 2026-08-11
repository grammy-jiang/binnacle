"""Atomic fsynced retained payload byte store."""

from __future__ import annotations

import asyncio
import hashlib
import os
import stat
from collections.abc import AsyncIterator, Hashable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from binnacle.domain.payload import PayloadLifecycle, PayloadMetadata
from binnacle.ports.payload import PayloadMetadataRepository


class PayloadStorageError(RuntimeError):
    pass


@dataclass(slots=True)
class _LockEntry:
    lock: asyncio.Lock
    users: int = 0


class _KeyedMutex:
    """Keep a bounded registry of mutexes for active payload/controller mutations."""

    def __init__(self) -> None:
        self._registry_lock = asyncio.Lock()
        self._entries: dict[Hashable, _LockEntry] = {}

    @asynccontextmanager
    async def hold(self, key: Hashable) -> AsyncIterator[None]:
        async with self._registry_lock:
            entry = self._entries.setdefault(key, _LockEntry(asyncio.Lock()))
            entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            async with self._registry_lock:
                entry.users -= 1
                if entry.users == 0 and not entry.lock.locked():
                    self._entries.pop(key, None)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class FilesystemPayloadStore:
    def __init__(
        self,
        *,
        directory: Path,
        repository: PayloadMetadataRepository,
        object_bytes_max: int,
        controller_bytes_max: int,
        append_chunk_bytes_max: int,
    ) -> None:
        self._directory = directory
        self._repository = repository
        self._object_bytes_max = object_bytes_max
        self._controller_bytes_max = controller_bytes_max
        self._append_chunk_bytes_max = append_chunk_bytes_max
        self._objects = directory / "objects"
        self._temporary = directory / "tmp"
        self._payload_mutations = _KeyedMutex()
        self._controller_quota_mutations = _KeyedMutex()

    async def initialize(self) -> None:
        for path in (self._directory, self._objects, self._temporary):
            path.mkdir(parents=True, exist_ok=True, mode=0o750)
            if path.is_symlink() or not path.is_dir():
                raise PayloadStorageError("payload directory is unsafe")

    def _paths(self, metadata: PayloadMetadata) -> tuple[Path, Path]:
        expected = PurePosixPath("objects") / metadata.payload_id
        if PurePosixPath(metadata.relative_path) != expected:
            raise PayloadStorageError("payload path is not implementation-owned")
        temporary = self._temporary / f"{metadata.payload_id}.part"
        final = self._objects / metadata.payload_id
        if temporary.parent != self._temporary or final.parent != self._objects:
            raise PayloadStorageError("payload path escapes its protected root")
        return temporary, final

    async def verify_all(self) -> tuple[PayloadMetadata, ...]:
        """Verify every metadata row and reject orphan/crash-window bytes."""

        metadata_rows = await self._repository.list_all()
        known_objects: set[str] = set()
        known_temporary: set[str] = set()
        for metadata in metadata_rows:
            temporary, final = self._paths(metadata)
            if metadata.lifecycle is PayloadLifecycle.COMPLETE:
                await self.verify(metadata.payload_id)
                known_objects.add(final.name)
            elif metadata.lifecycle is PayloadLifecycle.BUILDING:
                try:
                    info = temporary.lstat()
                except FileNotFoundError as exc:
                    raise PayloadStorageError("building payload bytes are missing") from exc
                if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                    raise PayloadStorageError("building payload path is unsafe")
                if info.st_size != metadata.decoded_byte_count:
                    raise PayloadStorageError("building payload bytes disagree with metadata")
                known_temporary.add(temporary.name)
            elif final.exists() or temporary.exists():
                raise PayloadStorageError("inactive payload retains unexpected bytes")
        self._verify_directory_entries(self._objects, known_objects)
        self._verify_directory_entries(self._temporary, known_temporary)
        return metadata_rows

    @staticmethod
    def _verify_directory_entries(directory: Path, expected: set[str]) -> None:
        observed: set[str] = set()
        for path in directory.iterdir():
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise PayloadStorageError("payload directory contains an unsafe entry")
            observed.add(path.name)
        if observed != expected:
            raise PayloadStorageError("payload directory contains orphan bytes")

    async def create(self, metadata: PayloadMetadata) -> PayloadMetadata:
        if metadata.lifecycle is not PayloadLifecycle.BUILDING or metadata.decoded_byte_count != 0:
            raise PayloadStorageError("new payload metadata must be empty and building")
        temporary, final = self._paths(metadata)
        if final.exists():
            raise PayloadStorageError("payload final path already exists")
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_directory(self._temporary)
        try:
            await self._repository.create(metadata)
        except Exception:
            temporary.unlink(missing_ok=True)
            _fsync_directory(self._temporary)
            raise
        return metadata

    async def append(self, payload_id: str, chunk: bytes) -> PayloadMetadata:
        if len(chunk) > self._append_chunk_bytes_max:
            raise PayloadStorageError("payload append chunk exceeds maximum")
        async with self._payload_mutations.hold(payload_id):
            metadata = await self._require(payload_id)
            if metadata.lifecycle is not PayloadLifecycle.BUILDING:
                raise PayloadStorageError("payload is not building")
            new_size = metadata.decoded_byte_count + len(chunk)
            if new_size > self._object_bytes_max:
                raise PayloadStorageError("payload object quota exceeded")
            controller_key = (metadata.controller_id, metadata.controller_epoch)
            async with self._controller_quota_mutations.hold(controller_key):
                controller_bytes = await self._repository.controller_bytes(*controller_key)
                if controller_bytes + len(chunk) > self._controller_bytes_max:
                    raise PayloadStorageError("payload controller quota exceeded")
                temporary, _ = self._paths(metadata)
                descriptor = os.open(
                    temporary,
                    os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
                )
                try:
                    written = 0
                    while written < len(chunk):
                        written += os.write(descriptor, chunk[written:])
                    # The database size may advance only after the appended bytes are
                    # durable.  Otherwise a crash can leave authoritative metadata
                    # ahead of the retained payload.
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                return await self._repository.update_building_size(payload_id, new_size)

    async def finalize(self, payload_id: str) -> PayloadMetadata:
        async with self._payload_mutations.hold(payload_id):
            metadata = await self._require(payload_id)
            temporary, final = self._paths(metadata)
            if metadata.lifecycle is PayloadLifecycle.COMPLETE:
                return await self.verify(payload_id)
            if metadata.lifecycle is not PayloadLifecycle.BUILDING:
                raise PayloadStorageError("payload cannot be finalized")
            descriptor = os.open(temporary, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            digest = hashlib.sha256()
            count = 0
            try:
                while block := os.read(descriptor, 1024 * 1024):
                    digest.update(block)
                    count += len(block)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            if count != metadata.decoded_byte_count:
                raise PayloadStorageError("payload bytes disagree with building metadata")
            os.link(temporary, final, follow_symlinks=False)
            os.unlink(temporary)
            _fsync_directory(self._objects)
            _fsync_directory(self._temporary)
            return await self._repository.complete(
                payload_id, byte_count=count, sha256=digest.hexdigest()
            )

    async def read_range(self, payload_id: str, start: int, end: int) -> bytes:
        metadata = await self.verify(payload_id)
        if start < 0 or end < start or end > metadata.decoded_byte_count:
            raise PayloadStorageError("payload range is invalid")
        _, final = self._paths(metadata)
        descriptor = os.open(final, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.lseek(descriptor, start, os.SEEK_SET)
            return os.read(descriptor, end - start)
        finally:
            os.close(descriptor)

    async def verify(self, payload_id: str) -> PayloadMetadata:
        metadata = await self._require(payload_id)
        if metadata.lifecycle is not PayloadLifecycle.COMPLETE or metadata.sha256 is None:
            raise PayloadStorageError("payload is not complete")
        _, final = self._paths(metadata)
        try:
            info = final.lstat()
        except FileNotFoundError as exc:
            raise PayloadStorageError("complete payload bytes are missing") from exc
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise PayloadStorageError("payload object path is unsafe")
        digest = hashlib.sha256(final.read_bytes()).hexdigest()
        if info.st_size != metadata.decoded_byte_count or digest != metadata.sha256:
            raise PayloadStorageError("complete payload bytes failed integrity verification")
        return metadata

    async def _require(self, payload_id: str) -> PayloadMetadata:
        metadata = await self._repository.get(payload_id)
        if metadata is None:
            raise PayloadStorageError("payload was not found")
        return metadata
