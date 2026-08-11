"""Atomic retained payload completion, quota, range, and corruption tests."""

from __future__ import annotations

import asyncio
import os
import secrets
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.phase4_support import intent, operation_runtime, owner

from binnacle.adapters.payload.filesystem import FilesystemPayloadStore, PayloadStorageError
from binnacle.adapters.payload.verify import find_orphan_payloads
from binnacle.adapters.sqlite.engine import DatabaseRuntime
from binnacle.adapters.sqlite.payload import SqlitePayloadMetadataRepository
from binnacle.domain.idempotency import IdempotencyKeyMode, validate_and_digest_key
from binnacle.domain.payload import PayloadKind, PayloadLifecycle, PayloadMetadata
from binnacle.ports.operation_store import CreateOrFindRequest


def _metadata(payload_id: str, operation_id: str) -> PayloadMetadata:
    return PayloadMetadata(
        payload_id=payload_id,
        operation_id=operation_id,
        controller_id="controller-fixture",
        controller_epoch=1,
        kind=PayloadKind.RESULT,
        lifecycle=PayloadLifecycle.BUILDING,
        relative_path=f"objects/{payload_id}",
        media_type="application/octet-stream",
        encoding="binary",
        decoded_byte_count=0,
        sha256=None,
        truncated=False,
        information_class="normal-result",
        retention_class="AR2",
        created_at=datetime.now(UTC),
    )


class _PausingPayloadReadRepository(SqlitePayloadMetadataRepository):
    """Hold the first metadata snapshot so a second append attempts the same race."""

    def __init__(self, runtime: DatabaseRuntime, payload_id: str) -> None:
        super().__init__(runtime)
        self._payload_id = payload_id
        self.payload_read_calls = 0
        self.first_read_entered = asyncio.Event()
        self.release_first_read = asyncio.Event()

    async def get(self, payload_id: str) -> PayloadMetadata | None:
        if payload_id != self._payload_id:
            return await super().get(payload_id)
        self.payload_read_calls += 1
        metadata = await super().get(payload_id)
        if self.payload_read_calls == 1:
            self.first_read_entered.set()
            await self.release_first_read.wait()
        return metadata


class _PausingControllerQuotaRepository(SqlitePayloadMetadataRepository):
    """Hold one quota snapshot while a second payload reaches controller admission."""

    def __init__(self, runtime: DatabaseRuntime, second_payload_id: str) -> None:
        super().__init__(runtime)
        self._second_payload_id = second_payload_id
        self.quota_read_calls = 0
        self.first_quota_read_entered = asyncio.Event()
        self.release_first_quota_read = asyncio.Event()
        self.second_metadata_read_entered = asyncio.Event()
        self.release_second_metadata_read = asyncio.Event()

    async def get(self, payload_id: str) -> PayloadMetadata | None:
        metadata = await super().get(payload_id)
        if payload_id == self._second_payload_id:
            self.second_metadata_read_entered.set()
            await self.release_second_metadata_read.wait()
        return metadata

    async def controller_bytes(self, controller_id: str, controller_epoch: int) -> int:
        self.quota_read_calls += 1
        value = await super().controller_bytes(controller_id, controller_epoch)
        if self.quota_read_calls == 1:
            self.first_quota_read_entered.set()
            await self.release_first_quota_read.wait()
        return value


@pytest.mark.anyio
async def test_payload_finalize_is_digest_truthful_and_idempotent(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operation_store):
        key = validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY)
        created = await operation_store.create_or_find(
            CreateOrFindRequest(key, owner(), intent(), "internal.synthetic", "1.0.0")
        )
        assert created.operation is not None
        repository = SqlitePayloadMetadataRepository(runtime)
        payloads = FilesystemPayloadStore(
            directory=tmp_path / "results",
            repository=repository,
            object_bytes_max=32,
            controller_bytes_max=64,
            append_chunk_bytes_max=8,
        )
        await payloads.initialize()
        metadata = _metadata("payload-fixture", created.operation.operation_id)
        await payloads.create(metadata)
        await payloads.append(metadata.payload_id, b"abcd")
        await payloads.append(metadata.payload_id, b"efgh")
        complete = await payloads.finalize(metadata.payload_id)
        assert complete.lifecycle is PayloadLifecycle.COMPLETE
        assert complete.decoded_byte_count == 8
        assert complete.sha256 == (
            "9c56cc51b374c3ba189210d5b6d4bf57790d351c96c47c02190ecf1e430635ab"
        )
        assert await payloads.read_range(metadata.payload_id, 2, 6) == b"cdef"
        assert await payloads.finalize(metadata.payload_id) == complete
        assert await payloads.verify_all() == (complete,)


@pytest.mark.anyio
async def test_payload_append_fsyncs_bytes_before_advancing_metadata(
    tmp_path: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operation_store):
        created = await operation_store.create_or_find(
            CreateOrFindRequest(
                validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY),
                owner(),
                intent(),
                "internal.synthetic",
                "1.0.0",
            )
        )
        assert created.operation is not None
        repository = SqlitePayloadMetadataRepository(runtime)
        payloads = FilesystemPayloadStore(
            directory=tmp_path / "results",
            repository=repository,
            object_bytes_max=32,
            controller_bytes_max=64,
            append_chunk_bytes_max=8,
        )
        await payloads.initialize()
        metadata = _metadata("durable-append", created.operation.operation_id)
        await payloads.create(metadata)

        events: list[str] = []
        original_fsync = os.fsync
        original_update = repository.update_building_size

        def tracked_fsync(descriptor: int) -> None:
            events.append("fsync")
            original_fsync(descriptor)

        async def tracked_update(payload_id: str, new_size: int) -> PayloadMetadata:
            events.append("metadata")
            return await original_update(payload_id, new_size)

        monkeypatch.setattr(os, "fsync", tracked_fsync)
        monkeypatch.setattr(repository, "update_building_size", tracked_update)

        updated = await payloads.append(metadata.payload_id, b"abcd")

        assert updated.decoded_byte_count == 4
        assert events == ["fsync", "metadata"]


@pytest.mark.anyio
async def test_concurrent_same_payload_appends_cannot_lose_metadata(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operation_store):
        created = await operation_store.create_or_find(
            CreateOrFindRequest(
                validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY),
                owner(),
                intent(),
                "internal.synthetic",
                "1.0.0",
            )
        )
        assert created.operation is not None
        metadata = _metadata("concurrent", created.operation.operation_id)
        repository = _PausingPayloadReadRepository(runtime, metadata.payload_id)
        payloads = FilesystemPayloadStore(
            directory=tmp_path / "results",
            repository=repository,
            object_bytes_max=32,
            controller_bytes_max=32,
            append_chunk_bytes_max=8,
        )
        await payloads.initialize()
        await payloads.create(metadata)

        first = asyncio.create_task(payloads.append(metadata.payload_id, b"aaaa"))
        await repository.first_read_entered.wait()
        second_started = asyncio.Event()

        async def second_append() -> PayloadMetadata:
            second_started.set()
            return await payloads.append(metadata.payload_id, b"bbbb")

        second = asyncio.create_task(second_append())
        await second_started.wait()
        await asyncio.sleep(0)
        assert repository.payload_read_calls == 1

        repository.release_first_read.set()
        first_result, second_result = await asyncio.gather(first, second)
        assert first_result.decoded_byte_count == 4
        assert second_result.decoded_byte_count == 8
        assert (tmp_path / "results/tmp/concurrent.part").read_bytes() == b"aaaabbbb"
        assert (await repository.get(metadata.payload_id)) == second_result


@pytest.mark.anyio
async def test_concurrent_payloads_cannot_overcommit_controller_quota(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operation_store):
        created = await operation_store.create_or_find(
            CreateOrFindRequest(
                validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY),
                owner(),
                intent(),
                "internal.synthetic",
                "1.0.0",
            )
        )
        assert created.operation is not None
        first_metadata = _metadata("quota-first", created.operation.operation_id)
        second_metadata = _metadata("quota-second", created.operation.operation_id)
        repository = _PausingControllerQuotaRepository(runtime, second_metadata.payload_id)
        payloads = FilesystemPayloadStore(
            directory=tmp_path / "results",
            repository=repository,
            object_bytes_max=8,
            controller_bytes_max=4,
            append_chunk_bytes_max=4,
        )
        await payloads.initialize()
        await payloads.create(first_metadata)
        await payloads.create(second_metadata)

        first = asyncio.create_task(payloads.append(first_metadata.payload_id, b"1111"))
        await repository.first_quota_read_entered.wait()
        second = asyncio.create_task(payloads.append(second_metadata.payload_id, b"2222"))
        await repository.second_metadata_read_entered.wait()
        repository.release_second_metadata_read.set()
        await asyncio.sleep(0)
        assert repository.quota_read_calls == 1

        repository.release_first_quota_read.set()
        first_result = await first
        assert first_result.decoded_byte_count == 4
        with pytest.raises(PayloadStorageError, match="controller quota"):
            await second
        assert await repository.controller_bytes("controller-fixture", 1) == 4
        assert (tmp_path / "results/tmp/quota-first.part").read_bytes() == b"1111"
        assert (tmp_path / "results/tmp/quota-second.part").read_bytes() == b""


@pytest.mark.anyio
async def test_quota_invalid_range_and_corruption_fail_closed(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operation_store):
        key = validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY)
        created = await operation_store.create_or_find(
            CreateOrFindRequest(key, owner(), intent(), "internal.synthetic", "1.0.0")
        )
        assert created.operation is not None
        repository = SqlitePayloadMetadataRepository(runtime)
        payloads = FilesystemPayloadStore(
            directory=tmp_path / "results",
            repository=repository,
            object_bytes_max=8,
            controller_bytes_max=8,
            append_chunk_bytes_max=4,
        )
        await payloads.initialize()
        metadata = _metadata("payload-fixture", created.operation.operation_id)
        await payloads.create(metadata)
        with pytest.raises(PayloadStorageError, match="chunk"):
            await payloads.append(metadata.payload_id, b"12345")
        await payloads.append(metadata.payload_id, b"1234")
        await payloads.append(metadata.payload_id, b"5678")
        with pytest.raises(PayloadStorageError, match="quota"):
            await payloads.append(metadata.payload_id, b"x")
        await payloads.finalize(metadata.payload_id)
        with pytest.raises(PayloadStorageError, match="range"):
            await payloads.read_range(metadata.payload_id, 2, 99)
        (tmp_path / "results/objects/payload-fixture").write_bytes(b"tampered")
        with pytest.raises(PayloadStorageError, match="integrity"):
            await payloads.verify(metadata.payload_id)


def test_orphan_detection_is_deterministic(tmp_path: Path) -> None:
    objects = tmp_path / "objects"
    objects.mkdir()
    (objects / "known").write_bytes(b"a")
    (objects / "orphan-b").write_bytes(b"b")
    (objects / "orphan-a").write_bytes(b"a")
    assert [item.name for item in find_orphan_payloads(tmp_path, frozenset({"objects/known"}))] == [
        "orphan-a",
        "orphan-b",
    ]


@pytest.mark.parametrize("payload_id", ("/tmp/escape", "../escape", "nested/escape"))
def test_payload_identifier_cannot_escape_implementation_roots(payload_id: str) -> None:
    with pytest.raises(ValueError, match="identifier"):
        _metadata(payload_id, "op-fixture")


@pytest.mark.anyio
async def test_fresh_process_payload_scan_rejects_orphan_bytes(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, _):
        repository = SqlitePayloadMetadataRepository(runtime)
        payloads = FilesystemPayloadStore(
            directory=tmp_path / "results",
            repository=repository,
            object_bytes_max=32,
            controller_bytes_max=64,
            append_chunk_bytes_max=8,
        )
        await payloads.initialize()
        (tmp_path / "results/objects/orphan").write_bytes(b"untracked")
        with pytest.raises(PayloadStorageError, match="orphan"):
            await payloads.verify_all()


@pytest.mark.anyio
async def test_payload_store_rejects_invalid_states_paths_and_controller_quota(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operation_store):
        created = await operation_store.create_or_find(
            CreateOrFindRequest(
                validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY),
                owner(),
                intent(),
                "internal.synthetic",
                "1.0.0",
            )
        )
        assert created.operation is not None
        repository = SqlitePayloadMetadataRepository(runtime)
        payloads = FilesystemPayloadStore(
            directory=tmp_path / "results",
            repository=repository,
            object_bytes_max=64,
            controller_bytes_max=4,
            append_chunk_bytes_max=64,
        )
        await payloads.initialize()
        first = _metadata("first", created.operation.operation_id)
        second = _metadata("second", created.operation.operation_id)
        await payloads.create(first)
        await payloads.append(first.payload_id, b"1234")
        await payloads.create(second)
        with pytest.raises(PayloadStorageError, match="controller quota"):
            await payloads.append(second.payload_id, b"x")
        await payloads.finalize(first.payload_id)
        with pytest.raises(PayloadStorageError, match="not building"):
            await payloads.append(first.payload_id, b"")
        with pytest.raises(PayloadStorageError, match="not complete"):
            await payloads.verify(second.payload_id)
        await repository.fail(second.payload_id)
        with pytest.raises(PayloadStorageError, match="cannot be finalized"):
            await payloads.finalize(second.payload_id)
        with pytest.raises(PayloadStorageError, match="not found"):
            await payloads.verify("missing")
        with pytest.raises(PayloadStorageError, match="empty and building"):
            await payloads.create(replace(second, lifecycle=PayloadLifecycle.FAILED))
        with pytest.raises(PayloadStorageError, match="empty and building"):
            await payloads.create(replace(second, decoded_byte_count=1))
        third = _metadata("third", created.operation.operation_id)
        (tmp_path / "results/objects/third").write_bytes(b"already-present")
        with pytest.raises(PayloadStorageError, match="already exists"):
            await payloads.create(third)
        object.__setattr__(third, "payload_id", "/tmp")
        object.__setattr__(third, "relative_path", "/tmp")
        with pytest.raises(PayloadStorageError, match="escapes"):
            payloads._paths(third)


@pytest.mark.anyio
async def test_payload_scan_rejects_every_building_crash_window(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operation_store):
        created = await operation_store.create_or_find(
            CreateOrFindRequest(
                validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY),
                owner(),
                intent(),
                "internal.synthetic",
                "1.0.0",
            )
        )
        assert created.operation is not None
        repository = SqlitePayloadMetadataRepository(runtime)
        payloads = FilesystemPayloadStore(
            directory=tmp_path / "results",
            repository=repository,
            object_bytes_max=64,
            controller_bytes_max=64,
            append_chunk_bytes_max=64,
        )
        await payloads.initialize()
        metadata = _metadata("building", created.operation.operation_id)
        await payloads.create(metadata)
        await payloads.append(metadata.payload_id, b"x")
        assert len(await payloads.verify_all()) == 1
        temporary = tmp_path / "results/tmp/building.part"
        temporary.write_bytes(b"xx")
        with pytest.raises(PayloadStorageError, match="disagree"):
            await payloads.verify_all()
        temporary.write_bytes(b"x")
        temporary.unlink()
        with pytest.raises(PayloadStorageError, match="missing"):
            await payloads.verify_all()
        temporary.symlink_to(tmp_path / "results/objects")
        with pytest.raises(PayloadStorageError, match="unsafe"):
            await payloads.verify_all()
        temporary.unlink()
        temporary.write_bytes(b"x")
        await repository.fail(metadata.payload_id)
        with pytest.raises(PayloadStorageError, match="inactive"):
            await payloads.verify_all()


@pytest.mark.anyio
async def test_payload_repository_rejects_missing_backward_and_conflicting_updates(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, operation_store):
        created = await operation_store.create_or_find(
            CreateOrFindRequest(
                validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY),
                owner(),
                intent(),
                "internal.synthetic",
                "1.0.0",
            )
        )
        assert created.operation is not None
        repository = SqlitePayloadMetadataRepository(runtime)
        with pytest.raises(RuntimeError, match="not building"):
            await repository.update_building_size("missing", 1)
        with pytest.raises(RuntimeError, match="not registered"):
            await repository.complete("missing", byte_count=0, sha256="a" * 64)
        with pytest.raises(RuntimeError, match="not registered"):
            await repository.fail("missing")
        first = _metadata("first", created.operation.operation_id)
        await repository.create(first)
        await repository.update_building_size(first.payload_id, 4)
        with pytest.raises(RuntimeError, match="backward"):
            await repository.update_building_size(first.payload_id, 3)
        completed = await repository.complete(first.payload_id, byte_count=4, sha256="a" * 64)
        assert completed.lifecycle is PayloadLifecycle.COMPLETE
        assert await repository.complete(first.payload_id, byte_count=4, sha256="a" * 64)
        with pytest.raises(RuntimeError, match="conflicts"):
            await repository.complete(first.payload_id, byte_count=5, sha256="b" * 64)
        with pytest.raises(RuntimeError, match="complete"):
            await repository.fail(first.payload_id)
        second = _metadata("second", created.operation.operation_id)
        await repository.create(second)
        await repository.fail(second.payload_id)
        with pytest.raises(RuntimeError, match="current lifecycle"):
            await repository.complete(second.payload_id, byte_count=0, sha256="c" * 64)


@pytest.mark.anyio
async def test_payload_initialization_rejects_symlinked_root(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (runtime, _):
        target = tmp_path / "target"
        target.mkdir()
        linked = tmp_path / "results"
        linked.symlink_to(target, target_is_directory=True)
        payloads = FilesystemPayloadStore(
            directory=linked,
            repository=SqlitePayloadMetadataRepository(runtime),
            object_bytes_max=64,
            controller_bytes_max=64,
            append_chunk_bytes_max=64,
        )
        with pytest.raises(PayloadStorageError, match="unsafe"):
            await payloads.initialize()
