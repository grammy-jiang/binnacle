"""Real bounded immutable allocations and worker-owned lifetime, synthetic files."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from weakref import ref

import pytest

from binnacle.features.commands.job_awareness import snapshots
from binnacle.features.commands.job_awareness.models import ErrorCode
from binnacle.features.commands.job_awareness.snapshots import (
    SnapshotMemory,
    SnapshotStore,
)
from tests.contracts.job_awareness.fakes import FakeHandleAuthority
from tests.unit.core.job_awareness.test_snapshots import (
    CountingCatalog,
    assert_error,
    enroll,
    setup_store,
)


def population(tmp_path, count=19):
    authority = FakeHandleAuthority()
    catalog = CountingCatalog()
    records = [
        enroll(catalog, tmp_path, i + 1, bytes([i]) * (1 << 20)) for i in range(count)
    ]
    grant = authority.issue(tuple(s.job for s, _ in records))
    memory = SnapshotMemory()
    store = SnapshotStore(authority, catalog, lambda: 1000, memory=memory)
    return records, grant, memory, store


def test_cache_saturation_pinned_leases(tmp_path):
    records, grant, memory, store = population(tmp_path, 17)
    leases = [store.open_verified(grant, s).value for s, _ in records[:16]]
    try:
        assert memory.stats().cache_bytes == 16 << 20
        assert memory.stats().pins == 16
        assert_error(
            store.open_verified(grant, records[16][0]), ErrorCode.QUOTA_EXCEEDED
        )
        assert memory.stats().cache_bytes == 16 << 20
        assert memory.stats().inflight_bytes == 0
        leases[0].__exit__(None, None, None)
        with store.open_verified(grant, records[16][0]).value as lease:
            assert len(lease.verified_bytes) == 1 << 20
            assert memory.stats().cache_bytes == 16 << 20
        with store.open_verified(grant, records[1][0]).value as same:
            assert same.verified_bytes is leases[1].verified_bytes
            assert memory.stats().cache_bytes == 16 << 20
    finally:
        for lease in leases:
            lease.__exit__(None, None, None)
    memory.evict_unpinned()
    assert memory.stats().cache_entries == 0


@pytest.mark.parametrize("eviction", ["admission", "maintenance"])
def test_closing_frame_cannot_retain_uncharged_payload(tmp_path, monkeypatch, eviction):
    # Preserve the 16-copy ratio with small real allocations. The full-size
    # saturation test separately checks the production 16 MiB limit.
    size = 32
    monkeypatch.setattr(snapshots, "CACHE_BYTES", 16 * size)
    authority = FakeHandleAuthority()
    catalog = CountingCatalog()
    records = [enroll(catalog, tmp_path, i + 1, bytes([i]) * size) for i in range(17)]
    grant = authority.issue(tuple(s.job for s, _ in records))
    memory = SnapshotMemory()
    store = SnapshotStore(authority, catalog, lambda: 1000, memory=memory)
    leases = [store.open_verified(grant, s).value for s, _ in records[:16]]
    retired = ref(leases[0]._cached)
    unlocked = Event()
    finish = Event()

    class PauseAfterUnlock:
        """Suspend the real closing frame after its final lock is released."""

        def __init__(self, lock):
            self.lock = lock

        def __enter__(self):
            return self.lock.__enter__()

        def __exit__(self, *args):
            self.lock.__exit__(*args)
            unlocked.set()
            assert finish.wait(5)

    original_lock = leases[0]._lock
    leases[0]._lock = PauseAfterUnlock(original_lock)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            closing = executor.submit(leases[0].__exit__, None, None, None)
            try:
                assert unlocked.wait(5)
                assert not closing.done()
                assert leases[0]._cached is None
                assert retired() is not None
                assert len(retired().data) == size
                assert memory.stats().pins == 15
                if eviction == "maintenance":
                    memory.evict_unpinned()
                    assert memory.stats().cache_bytes == 15 * size
                with store.open_verified(grant, records[16][0]).value as replacement:
                    assert len(replacement.verified_bytes) == size
                    assert memory.stats().cache_bytes == 16 * size
                    assert memory.stats().inflight_bytes == 0
                    # Inspect payload lifetime, not just the pool counters.
                    # A suspended frame may retain metadata, but no old bytes.
                    assert retired() is None or len(retired().data) == 0
            finally:
                finish.set()
            closing.result(5)
        assert retired() is None
        leases[0]._lock = original_lock
        with pytest.raises(RuntimeError, match="lease"):
            _ = leases[0].verified_bytes
        leases[0].__exit__(None, None, None)
        assert memory.stats().pins == 15
        with store.open_verified(grant, records[0][0]).value as reopened:
            assert reopened.verified_bytes == bytes([0]) * size
            assert memory.stats().cache_bytes == 16 * size
    finally:
        leases[0]._lock = original_lock
        for lease in leases:
            lease.__exit__(None, None, None)
        memory.evict_unpinned()
    assert memory.stats().cache_bytes == memory.stats().pins == 0


def test_aggregate_inflight_reservation(tmp_path):
    records, grant, memory, store = population(tmp_path, 3)
    entered = [Event(), Event()]
    release = Event()

    def barrier(index):
        def block():
            entered[index].set()
            assert release.wait(5)

        return block

    for i in range(2):
        records[i][1].before_read = barrier(i)

    def read(index):
        with store.open_verified(grant, records[index][0]).value as lease:
            assert len(lease.verified_bytes) == 1 << 20

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(read, i) for i in range(2)]
        try:
            assert all(event.wait(5) for event in entered)
            assert memory.stats().inflight_bytes == 2 << 20
            assert_error(
                store.open_verified(grant, records[2][0]), ErrorCode.QUOTA_EXCEEDED
            )
            assert records[2][1].reads == 0
            assert (
                memory.stats().cache_bytes + memory.stats().inflight_bytes <= 18 << 20
            )
        finally:
            release.set()
        for future in futures:
            future.result(5)
    assert memory.stats().inflight_bytes == memory.stats().pins == 0
    assert memory.stats().cache_bytes == 2 << 20


def test_transfer_failure_and_worker_exception(tmp_path):
    records, grant, memory, store = population(tmp_path)
    leases = [store.open_verified(grant, s).value for s, _ in records[:16]]
    entered = [Event(), Event()]
    release = Event()

    def barrier(index):
        def block():
            entered[index].set()
            assert release.wait(5)

        return block

    for index in range(2):
        records[16 + index][1].before_read = barrier(index)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(store.open_verified, grant, records[index][0])
            for index in (16, 17)
        ]
        try:
            assert all(event.wait(5) for event in entered)
            assert (
                memory.stats().cache_bytes + memory.stats().inflight_bytes == 18 << 20
            )
            assert_error(
                store.open_verified(grant, records[18][0]), ErrorCode.QUOTA_EXCEEDED
            )
            assert records[18][1].reads == 0
        finally:
            release.set()
        for future in futures:
            assert_error(future.result(5), ErrorCode.QUOTA_EXCEEDED)
    assert memory.stats().inflight_bytes == 0

    def fail():
        raise RuntimeError("synthetic worker failed")

    records[18][1].before_read = fail
    with pytest.raises(RuntimeError, match="synthetic worker"):
        store.open_verified(grant, records[18][0])
    assert memory.stats().inflight_bytes == 0
    for lease in leases:
        lease.__exit__(None, None, None)
    memory.evict_unpinned()
    assert memory.stats().cache_bytes == 0


@pytest.mark.parametrize("phase", ["reading", "leased"])
def test_cancelled_awaiter_keeps_worker_charge(tmp_path, phase):
    _, _, snap, source, grant, memory, store = setup_store(tmp_path, b"x" * (1 << 20))

    async def scenario():
        entered = Event()
        ready = asyncio.Event()
        release = Event()
        loop = asyncio.get_running_loop()

        def block():
            entered.set()
            assert release.wait(5)

        if phase == "reading":
            source.before_read = block

        def worker():
            with store.open_verified(grant, snap).value as lease:
                if phase == "leased":
                    block()
                assert len(lease.verified_bytes) == 1 << 20

        with ThreadPoolExecutor(max_workers=1) as executor:
            underlying = executor.submit(worker)

            async def await_worker():
                ready.set()
                await asyncio.shield(asyncio.wrap_future(underlying))

            task = asyncio.create_task(await_worker())
            try:
                await ready.wait()
                assert entered.wait(5)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                if phase == "reading":
                    assert memory.stats().inflight_bytes == 1 << 20
                else:
                    assert memory.stats().pins == 1
                    memory.evict_unpinned()
                    assert memory.stats().cache_bytes == 1 << 20
                sentinel = asyncio.Event()
                loop.call_soon(sentinel.set)
                await sentinel.wait()
                assert not underlying.done()
            finally:
                release.set()
            underlying.result(5)
        assert memory.stats().pins == memory.stats().inflight_bytes == 0

    asyncio.run(scenario())


def test_retention_and_restart(tmp_path):
    authority, catalog, snap, source, grant, memory, store = setup_store(tmp_path, b"")
    lease = store.open_verified(grant, snap).value
    authority.now_ms = snap.retained_until_ms
    assert_error(store.open_verified(grant, snap), ErrorCode.OUTPUT_EXPIRED)
    with pytest.raises(RuntimeError, match="lease"):
        _ = lease.verified_bytes
    lease.__exit__(None, None, None)
    source.path.unlink()
    assert_error(store.open_verified(grant, snap), ErrorCode.OUTPUT_EXPIRED)
    # Expiry tombstone survives payload loss; no catalog resurrection.
    assert_error(
        catalog.register(catalog.lookup(snap.job).observation, source),
        ErrorCode.OUTPUT_CHANGED,
    )
    restart = SnapshotStore(
        authority, CountingCatalog(), lambda: authority.now_ms, memory=memory
    )
    assert_error(restart.open_verified(grant, snap), ErrorCode.SOURCE_UNSEALED)


def test_missing_is_not_empty_and_exception_cleanup(tmp_path):
    _, _, snap, source, grant, memory, store = setup_store(tmp_path, b"")
    source.path.unlink()
    assert_error(store.open_verified(grant, snap), ErrorCode.SOURCE_UNAVAILABLE)
    assert memory.stats().pins == memory.stats().inflight_bytes == 0
    source.path.write_bytes(b"")
    source.identity = source.signature()
    # Missing source invalidates admission; a later path cannot revive the seal.
    assert_error(store.open_verified(grant, snap), ErrorCode.SOURCE_UNAVAILABLE)


def test_clock_rollback_and_closed_lease(tmp_path):
    authority, _, snap, _, grant, _, store = setup_store(tmp_path)
    lease = store.open_verified(grant, snap).value
    authority.now_ms = 999
    with pytest.raises(RuntimeError, match="lease"):
        _ = lease.verified_bytes
    lease.__exit__(None, None, None)
    with pytest.raises(RuntimeError, match="lease"):
        lease.__enter__()


def test_process_default_budget_is_shared(tmp_path):
    records, grant, _, first = population(tmp_path, 2)
    second = SnapshotStore(first.authority, first.catalog, lambda: 1000)
    third = SnapshotStore(first.authority, first.catalog, lambda: 1000)
    assert second.memory is third.memory
    with second.open_verified(grant, records[0][0]).value:
        assert third.memory.stats().pins == 1
    third.memory.evict_unpinned()


def test_failed_context_entry_releases_pin(tmp_path):
    authority, _, snap, _, grant, memory, store = setup_store(tmp_path)
    lease = store.open_verified(grant, snap).value
    authority.now_ms = snap.retained_until_ms
    with pytest.raises(RuntimeError, match="lease"), lease:
        pytest.fail("expired lease entered")
    assert memory.stats().pins == 0


def test_one_byte_over_inflight_and_duplicate_transfer(tmp_path):
    records, grant, memory, store = population(tmp_path, 2)
    # Two concurrent opens of the SAME snapshot have separate read reservations
    # but must share one cached immutable allocation after both complete.
    entered = [Event(), Event()]
    release = Event()
    from threading import Lock

    lock = Lock()
    calls = 0

    def block():
        nonlocal calls
        with lock:
            index = calls
            calls += 1
        entered[index].set()
        assert release.wait(5)

    records[0][1].before_read = block
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(store.open_verified, grant, records[0][0]) for _ in range(2)
        ]
        try:
            assert all(event.wait(5) for event in entered)
            assert not memory.reserve(1)
            assert memory.stats().inflight_bytes == 2 << 20
        finally:
            release.set()
        leases = [future.result(5).value for future in futures]
    try:
        assert leases[0].verified_bytes is leases[1].verified_bytes
        assert memory.stats().cache_bytes == 1 << 20
        assert memory.stats().inflight_bytes == 0
        assert memory.stats().pins == 2
    finally:
        for lease in leases:
            lease.__exit__(None, None, None)
