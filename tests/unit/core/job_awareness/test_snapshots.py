"""Synthetic files only. These adapters never inspect a production spool."""

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from binnacle.features.commands.job_awareness.models import (
    BoundaryError,
    ErrorCode,
    Failure,
    JobRef,
    Observation,
    ObservationState,
    OutputSnapshot,
    SourceKind,
    Success,
    TerminalKind,
    TerminalOutcome,
)
from binnacle.features.commands.job_awareness.snapshots import (
    SnapshotMemory,
    SnapshotStore,
    TrustedCatalog,
    read_page,
)
from tests.contracts.job_awareness.fakes import FakeHandleAuthority


class FilePayload:
    """Trusted test adapter: bind a temporary file identity and bounded length.

    read() transfers ownership of one immutable allocation. It keeps no payload.
    Same-content path replacement also invalidates the controller's seal.
    """

    def __init__(self, path: Path):
        self.path = path
        self.identity = self.signature()
        self.reads = 0
        self.bytes_read = 0
        self.before_read = None

    def signature(self):
        stat = self.path.stat()
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)

    def read(self, length):
        self.reads += 1
        if self.before_read:
            self.before_read()
        try:
            if self.signature() != self.identity or self.identity[2] != length:
                return Failure(BoundaryError(ErrorCode.OUTPUT_CHANGED))
            with self.path.open("rb", buffering=0) as stream:
                data = stream.read(length)
            self.bytes_read += len(data)
            if self.signature() != self.identity or len(data) != length:
                return Failure(BoundaryError(ErrorCode.OUTPUT_CHANGED))
            return Success(data)
        except FileNotFoundError:
            return Failure(BoundaryError(ErrorCode.SOURCE_UNAVAILABLE))


class CountingCatalog(TrustedCatalog):
    def __init__(self):
        super().__init__()
        self.lookups = 0

    def lookup(self, job):
        self.lookups += 1
        return super().lookup(job)


def job_ref(number=1, incarnation=1):
    return JobRef("ja1_" + "1" * 32, f"{number:012x}", f"g1_{incarnation:032x}")


def enroll(catalog, tmp_path, number=1, payload=b"output", *, job=None, terminal=None):
    job = job or job_ref(number)
    path = tmp_path / f"payload-{number}-{job.incarnation}"
    path.write_bytes(payload)
    source = FilePayload(path)
    snapshot = OutputSnapshot(
        job,
        hashlib.sha256(payload).hexdigest(),
        len(payload),
        terminal or TerminalOutcome(TerminalKind.EXIT_CODE, 0),
        1000,
        11000,
        SourceKind.CONTROLLER_SEALED_SYNTHETIC,
        f"{number:032x}",
    )
    result = catalog.register(
        Observation(job, ObservationState.TERMINAL, snapshot.terminal, snapshot), source
    )
    assert isinstance(result, Success)
    return snapshot, source


def setup_store(tmp_path, payload=b"output"):
    authority = FakeHandleAuthority()
    catalog = CountingCatalog()
    snapshot, source = enroll(catalog, tmp_path, payload=payload)
    grant = authority.issue((snapshot.job,))
    memory = SnapshotMemory()
    store = SnapshotStore(authority, catalog, lambda: authority.now_ms, memory=memory)
    return authority, catalog, snapshot, source, grant, memory, store


def assert_error(result, code):
    assert result == Failure(BoundaryError(code))


@pytest.mark.parametrize("change", ["truncate", "append", "corrupt", "replace"])
def test_changed_bytes(tmp_path, change):
    _, _, snap, source, grant, memory, store = setup_store(tmp_path)
    lease = store.open_verified(grant, snap).value
    if change == "truncate":
        source.path.write_bytes(b"")
    elif change == "append":
        with source.path.open("ab") as stream:
            stream.write(b"!")
    elif change == "corrupt":
        # Preserve metadata to force the digest guard, not just adapter checks.
        source.path.write_bytes(b"OUTPUT")
        source.identity = source.signature()
    else:
        replacement = tmp_path / "replacement"
        replacement.write_bytes(b"output")
        replacement.replace(source.path)
    assert_error(store.open_verified(grant, snap), ErrorCode.OUTPUT_CHANGED)
    with pytest.raises(RuntimeError, match="lease"):
        _ = lease.verified_bytes
    lease.__exit__(None, None, None)
    reads = source.reads
    assert_error(store.open_verified(grant, snap), ErrorCode.OUTPUT_CHANGED)
    assert source.reads == reads
    assert memory.stats().inflight_bytes == 0


def test_reuse_and_replacement(tmp_path):
    authority, catalog, snap, source, grant, _, store = setup_store(tmp_path)
    duplicate = catalog.register(
        Observation(snap.job, ObservationState.TERMINAL, snap.terminal, snap), source
    )
    assert_error(duplicate, ErrorCode.OUTPUT_CHANGED)
    new, _ = enroll(catalog, tmp_path, 2, b"new", job=job_ref(1, 2))
    assert_error(store.open_verified(grant, new), ErrorCode.DENIED)
    fresh = authority.issue((new.job,))
    with store.open_verified(fresh, new).value as lease:
        assert lease.verified_bytes == b"new"
    for forged in (
        replace(snap, sha256="0" * 64),
        replace(snap, seal_id="f" * 32),
        replace(snap, retained_until_ms=12000),
        replace(snap, terminal=TerminalOutcome(TerminalKind.EXIT_CODE, 2)),
    ):
        assert_error(store.open_verified(grant, forged), ErrorCode.OUTPUT_CHANGED)
    with store.open_verified(grant, snap).value as lease:
        assert lease.verified_bytes == b"output"


@pytest.mark.parametrize(
    "payload", [b"", b"\xff", b"a" * 16384, b"a" * 16383 + "€🙂".encode()]
)
def test_binary_and_empty(tmp_path, payload):
    _, _, snap, _, grant, _, store = setup_store(tmp_path, payload)
    result = store.open_verified(grant, snap)
    with result.value as lease:
        pages = [
            read_page(lease, start).value for start in range(0, len(payload), 16384)
        ]
        if not payload:
            pages = [read_page(lease, 0).value]
        assert b"".join(pages) == payload
        assert hashlib.sha256(lease.verified_bytes).hexdigest() == snap.sha256
        for start in (-1, True, 1, len(payload) + 16384):
            assert_error(read_page(lease, start), ErrorCode.INVALID_SELECTOR)
    with pytest.raises(RuntimeError, match="lease"):
        _ = result.value.verified_bytes
    result.value.__exit__(None, None, None)  # Idempotent; no negative pins.


def test_snapshot_limit(tmp_path):
    _, catalog, snap, source, grant, memory, store = setup_store(
        tmp_path, b"x" * (1 << 20)
    )
    with store.open_verified(grant, snap).value as lease:
        assert len(lease.verified_bytes) == 1 << 20
    assert memory.stats().cache_bytes == 1 << 20
    source.path.write_bytes(b"x" * ((1 << 20) + 1))
    assert_error(store.open_verified(grant, snap), ErrorCode.OUTPUT_CHANGED)
    assert source.bytes_read == 1 << 20
    # A claimed oversize seal is rejected by the frozen record before enrollment.
    with pytest.raises(ValueError):
        replace(snap, byte_length=(1 << 20) + 1)
    assert catalog.lookups > 0


def test_evict_reopen_accounting(tmp_path):
    authority = FakeHandleAuthority()
    catalog = CountingCatalog()
    records = [
        enroll(catalog, tmp_path, i + 1, bytes([i]) * (1 << 20)) for i in range(17)
    ]
    grant = authority.issue(tuple(s.job for s, _ in records))
    memory = SnapshotMemory()
    store = SnapshotStore(authority, catalog, lambda: 1000, memory=memory)
    for i in range(64):
        snap, source = records[i % 17]
        before = source.bytes_read
        with store.open_verified(grant, snap).value as lease:
            assert len(lease.verified_bytes) == 1 << 20
        assert source.bytes_read - before == 1 << 20
        assert memory.stats().cache_bytes <= 16 << 20
        assert memory.stats().inflight_bytes == 0
        assert memory.stats().cache_entries <= 16
    # Entry 0 was evicted during the last sweep. Reopen must verify again.
    snap, source = records[0]
    source.path.write_bytes(b"z" * (1 << 20))
    source.identity = source.signature()
    assert_error(store.open_verified(grant, snap), ErrorCode.OUTPUT_CHANGED)
    memory.evict_unpinned()
    assert memory.stats().cache_bytes == memory.stats().inflight_bytes == 0


def test_catalog_cap_and_empty_cache_bound(tmp_path):
    authority = FakeHandleAuthority()
    catalog = CountingCatalog()
    records = [enroll(catalog, tmp_path, i, b"") for i in range(1, 101)]
    grant = authority.issue(tuple(s.job for s, _ in records))
    memory = SnapshotMemory()
    store = SnapshotStore(authority, catalog, lambda: 1000, memory=memory)
    for snap, _ in records:
        with store.open_verified(grant, snap).value as lease:
            assert lease.verified_bytes == b""
    extra = Observation(job_ref(101), ObservationState.RUNNING, None, None)
    assert_error(catalog.register(extra), ErrorCode.QUOTA_EXCEEDED)
    assert memory.stats().cache_entries == 100
    assert memory.stats().cache_bytes == 0


def test_page_is_borrowed_without_an_extra_payload_allocation(tmp_path):
    _, _, snap, _, grant, _, store = setup_store(tmp_path, b"a" * 20000)
    with store.open_verified(grant, snap).value as lease:
        page = read_page(lease, 0).value
        assert isinstance(page, memoryview)
        assert page.readonly and page.obj is lease.verified_bytes
        assert len(page) == 16384


def test_expiry_during_payload_read_releases_reservation(tmp_path):
    authority, _, snap, source, grant, memory, store = setup_store(tmp_path)

    def expire():
        authority.now_ms = snap.retained_until_ms

    source.before_read = expire
    assert_error(store.open_verified(grant, snap), ErrorCode.OUTPUT_EXPIRED)
    assert (
        memory.stats().pins
        == memory.stats().inflight_bytes
        == memory.stats().cache_bytes
        == 0
    )


def test_wrong_bounded_digest_length_and_adapter_error(tmp_path):
    from binnacle.features.commands.job_awareness.models import Result

    class BrokenPayload:
        def __init__(self, value):
            self.value = value

        def read(self, length: int) -> Result[bytes]:
            if self.value == "error":
                raise PermissionError("private path must not escape")
            return Success(self.value)

    authority = FakeHandleAuthority()
    for i, value in enumerate((b"trunc", b"OUTPUT", "error"), 1):
        catalog = CountingCatalog()
        snap, source = enroll(catalog, tmp_path, i)
        other_catalog = CountingCatalog()
        other_catalog.register(
            catalog.lookup(snap.job).observation, BrokenPayload(value)
        )
        grant = authority.issue((snap.job,))
        memory = SnapshotMemory()
        store = SnapshotStore(authority, other_catalog, lambda: 1000, memory=memory)
        expected = (
            ErrorCode.SOURCE_UNAVAILABLE
            if value == "error"
            else ErrorCode.OUTPUT_CHANGED
        )
        assert_error(store.open_verified(grant, snap), expected)
        assert memory.stats().cache_bytes == memory.stats().inflight_bytes == 0
        assert source.reads == 0


def test_catalog_requires_explicit_source_and_unique_seal(tmp_path):
    _, catalog, snap, source, _, _, _ = setup_store(tmp_path)
    obs = Observation(job_ref(2), ObservationState.RUNNING, None, None)
    assert_error(catalog.register(obs, source), ErrorCode.SOURCE_UNSEALED)
    second = replace(snap, job=job_ref(2))
    obs = Observation(second.job, ObservationState.TERMINAL, second.terminal, second)
    assert_error(catalog.register(obs), ErrorCode.SOURCE_UNSEALED)
    assert_error(catalog.register(obs, source), ErrorCode.OUTPUT_CHANGED)
