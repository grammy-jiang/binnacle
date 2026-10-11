"""Inert synthetic snapshot admission and worker-owned immutable leases.

Only a trusted fixture controller enrolls seals. No filesystem, backend, worker
executor, or public tool is constructed here. Payload adapters live in tests.
The adapter transfers one immutable allocation and must enforce exact bounded
length and source identity before/after reading. A catalog is an incarnation
registry: losing it denies reads; constructing OutputSnapshot never restores it.
"""

import hashlib
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from types import TracebackType
from typing import Protocol

from binnacle.features.commands.job_awareness.models import (
    MAX_INTEGER,
    MAX_SNAPSHOT_BYTES,
    PAGE_BYTES,
    AuthorityDecision,
    BoundaryError,
    ErrorCode,
    Failure,
    JobRef,
    Observation,
    OutputSnapshot,
    Result,
    Scope,
    Success,
    VerifiedRunGrant,
)
from binnacle.features.commands.job_awareness.ports import (
    HandleAuthorityPort,
    SnapshotLease,
    SnapshotLeaseResult,
)

CACHE_BYTES = 16 * MAX_SNAPSHOT_BYTES
INFLIGHT_BYTES = 2 * MAX_SNAPSHOT_BYTES
CATALOG_ENTRIES = 100


def failure(code: ErrorCode) -> Failure:
    return Failure(BoundaryError(code))


class SealedPayload(Protocol):
    """Trusted synthetic adapter, never supplied by a request.

    read must allocate at most length bytes, return exact immutable bytes or a
    fixed failure, and retain no buffers. It must reject changed file identity,
    length and concurrent modification. No eager read on adapter construction
    or metadata lookup. The store separately verifies length and SHA256.
    """

    def read(self, length: int) -> Result[bytes]: ...


@dataclass(eq=False)
class CatalogEntry:
    observation: Observation
    source: SealedPayload | None
    invalid: ErrorCode | None = None


class TrustedCatalog:
    """Controller-only bounded metadata registry. Never discovers jobs.

    Sealed entries cannot be replaced, deleted or reused, including tombstones.
    Unsealed state may change until the controller explicitly enrolls a seal.
    A fresh run uses a fresh catalog and namespace. The 100-entry total bound
    also enforces the per-run snapshot count and 100 MiB payload limits.
    """

    def __init__(self) -> None:
        self._entries: dict[JobRef, CatalogEntry] = {}
        self._seals: set[str] = set()
        self._lock = RLock()

    def register(
        self, observation: Observation, source: SealedPayload | None = None
    ) -> Result[None]:
        snapshot = observation.snapshot
        if (snapshot is None) != (source is None):
            return failure(ErrorCode.SOURCE_UNSEALED)
        with self._lock:
            prior = self._entries.get(observation.job)
            if prior is not None and prior.observation.snapshot is not None:
                return failure(ErrorCode.OUTPUT_CHANGED)
            if snapshot is not None and snapshot.seal_id in self._seals:
                return failure(ErrorCode.OUTPUT_CHANGED)
            if prior is None and len(self._entries) >= CATALOG_ENTRIES:
                return failure(ErrorCode.QUOTA_EXCEEDED)
            self._entries[observation.job] = CatalogEntry(observation, source)
            if snapshot is not None:
                self._seals.add(snapshot.seal_id)
        return Success(None)

    def lookup(self, job: JobRef) -> CatalogEntry | None:
        with self._lock:
            return self._entries.get(job)

    def status(self, entry: CatalogEntry, now_ms: int) -> ErrorCode | None:
        with self._lock:
            snapshot = entry.observation.snapshot
            if snapshot is not None and now_ms >= snapshot.retained_until_ms:
                entry.invalid = ErrorCode.OUTPUT_EXPIRED
            return entry.invalid

    def invalidate(self, entry: CatalogEntry, code: ErrorCode) -> None:
        with self._lock:
            if entry.invalid is None:
                entry.invalid = code


class SnapshotClock:
    """Fail closed on invalid time or rollback; no wall-clock heuristic."""

    def __init__(self, clock: Callable[[], int]) -> None:
        self._clock = clock
        self._high_water = 0
        self._unsafe = False
        self._lock = RLock()

    def read(self) -> Result[int]:
        with self._lock:
            now = self._clock()
            if type(now) is not int or not self._high_water <= now <= MAX_INTEGER:
                self._unsafe = True
            if self._unsafe:
                return failure(ErrorCode.CLOCK_UNSAFE)
            self._high_water = now
            return Success(now)


@dataclass(frozen=True)
class MemoryStats:
    cache_bytes: int
    inflight_bytes: int
    cache_entries: int
    pins: int


@dataclass
class _Cached:
    data: bytes
    pins: int = 0


class SnapshotMemory:
    """One shared pool per process, including pinned copies and cancelled work.

    Admission never queues. All payload allocations require a prior reservation.
    Cache eviction scans at most 100 metadata entries. Shared copies count once;
    eviction clears retired payloads before releasing their byte charge, even
    when a closing frame still holds the cache record after its final unpin.
    Explicit eviction is controller maintenance, never a hint-path action.
    """

    def __init__(self) -> None:
        self._cache: OrderedDict[CatalogEntry, _Cached] = OrderedDict()
        self._cache_bytes = 0
        self._inflight_bytes = 0
        self._inflight_count = 0
        self._lock = RLock()

    def stats(self) -> MemoryStats:
        with self._lock:
            return MemoryStats(
                self._cache_bytes,
                self._inflight_bytes,
                len(self._cache),
                sum(c.pins for c in self._cache.values()),
            )

    def reserve(self, length: int) -> bool:
        with self._lock:
            if (
                not 0 <= length <= MAX_SNAPSHOT_BYTES
                or self._inflight_bytes + length > INFLIGHT_BYTES
                or self._inflight_count >= 2
            ):
                return False
            self._inflight_bytes += length
            self._inflight_count += 1
            return True

    def release(self, length: int) -> None:
        with self._lock:
            self._inflight_bytes -= length
            self._inflight_count -= 1

    def _drop(self, entry: CatalogEntry) -> None:
        """Caller holds the pool lock and has checked that the entry is unpinned."""
        removed = self._cache.pop(entry)
        length = len(removed.data)
        # A suspended unpin/close frame can still reference this record. Clear
        # its payload under the lock before any admission can reuse the charge.
        removed.data = b""
        self._cache_bytes -= length

    def admit(self, entry: CatalogEntry, data: bytes) -> tuple[_Cached | None, bool]:
        """Pin or transfer the reservation atomically. Caller owns failed bytes."""
        with self._lock:
            cached = self._cache.get(entry)
            if cached is not None:
                cached.pins += 1
                self._cache.move_to_end(entry)
                return cached, False
            needed = len(data)
            # One bounded pass, no retained victim list or allocation retry.
            for victim in tuple(self._cache):
                if (
                    self._cache_bytes + needed <= CACHE_BYTES
                    and len(self._cache) < CATALOG_ENTRIES
                ):
                    break
                if self._cache[victim].pins == 0:
                    self._drop(victim)
            if (
                self._cache_bytes + needed > CACHE_BYTES
                or len(self._cache) >= CATALOG_ENTRIES
            ):
                return None, False
            cached = _Cached(data, 1)
            self._cache[entry] = cached
            self._cache_bytes += needed
            self.release(needed)
            return cached, True

    def unpin(self, cached: _Cached) -> None:
        with self._lock:
            cached.pins -= 1

    def evict_unpinned(self) -> None:
        with self._lock:
            for entry in tuple(self._cache):
                if self._cache[entry].pins == 0:
                    self._drop(entry)


_PROCESS_MEMORY = SnapshotMemory()


class _Lease:
    def __init__(
        self,
        store: "SnapshotStore",
        entry: CatalogEntry,
        snapshot: OutputSnapshot,
        cached: _Cached,
    ) -> None:
        self._store = store
        self._entry = entry
        self._snapshot = snapshot
        self._cached: _Cached | None = cached
        self._lock = RLock()

    @property
    def snapshot(self) -> OutputSnapshot:
        return self._snapshot

    @property
    def verified_bytes(self) -> bytes:
        with self._lock:
            if self._cached is None or self._store.live(self._entry) is not None:
                raise RuntimeError("Snapshot lease is no longer valid")
            return self._cached.data

    def __enter__(self) -> SnapshotLease:
        try:
            _ = self.verified_bytes
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        with self._lock:
            cached, self._cached = self._cached, None
            if cached is not None:
                self._store.memory.unpin(cached)


class SnapshotStore:
    """READ admission precedes all catalog and payload access, on every call.

    Call synchronously inside an admitted worker. The worker must context-close
    its lease in finally, even when its async awaiter is cancelled. Never return
    an unconsumed lease across a cancellable executor await. I1 still rechecks
    authority, snapshot and retention inside its own commit transaction.
    """

    def __init__(
        self,
        authority: HandleAuthorityPort,
        catalog: TrustedCatalog,
        clock: Callable[[], int],
        *,
        memory: SnapshotMemory | None = None,
    ) -> None:
        self.authority = authority
        self.catalog = catalog
        self.clock = SnapshotClock(clock)
        self.memory = _PROCESS_MEMORY if memory is None else memory

    def live(self, entry: CatalogEntry) -> ErrorCode | None:
        now = self.clock.read()
        if isinstance(now, Failure):
            return now.error.code
        snapshot = entry.observation.snapshot
        if snapshot is None:
            return ErrorCode.SOURCE_UNSEALED
        if now.value < snapshot.sealed_at_ms:
            return ErrorCode.CLOCK_UNSAFE
        return self.catalog.status(entry, now.value)

    def open_verified(
        self, grant: VerifiedRunGrant, snapshot: OutputSnapshot
    ) -> SnapshotLeaseResult:
        if (
            self.authority.check(grant, snapshot.job, frozenset({Scope.READ}))
            is not AuthorityDecision.AUTHORIZED
        ):
            return failure(ErrorCode.DENIED)
        entry = self.catalog.lookup(snapshot.job)
        if entry is None or entry.observation.snapshot is None or entry.source is None:
            return failure(ErrorCode.SOURCE_UNSEALED)
        if entry.observation.snapshot != snapshot:
            return failure(ErrorCode.OUTPUT_CHANGED)
        invalid = self.live(entry)
        if invalid is not None:
            return failure(invalid)
        length = snapshot.byte_length
        if not self.memory.reserve(length):
            return failure(ErrorCode.QUOTA_EXCEEDED)
        transferred = False
        data: bytes | None = None
        try:
            result = entry.source.read(length)
            if isinstance(result, Failure):
                self.catalog.invalidate(entry, result.error.code)
                return result
            data = result.value
            del result  # No extra payload owner survives releasing the charge.
            if (
                type(data) is not bytes
                or len(data) != length
                or hashlib.sha256(data).hexdigest() != snapshot.sha256
            ):
                self.catalog.invalidate(entry, ErrorCode.OUTPUT_CHANGED)
                return failure(ErrorCode.OUTPUT_CHANGED)
            invalid = self.live(entry)
            if invalid is not None:
                return failure(invalid)
            cached, transferred = self.memory.admit(entry, data)
            if cached is None:
                return failure(ErrorCode.QUOTA_EXCEEDED)
            return Success(_Lease(self, entry, snapshot, cached))
        except OSError:
            self.catalog.invalidate(entry, ErrorCode.SOURCE_UNAVAILABLE)
            return failure(ErrorCode.SOURCE_UNAVAILABLE)
        finally:
            data = None
            if not transferred:
                self.memory.release(length)


def read_page(lease: SnapshotLease, start: int) -> Result[memoryview]:
    """Canonical raw-byte page for I1 to wrap/prove; no receipt or proof issued.

    Returned pages are read-only borrowed views, <=16 KiB, with no payload
    allocation. Do not retain a view or verified_bytes beyond the lease. I1
    accounts for envelope serialization in its own admitted worker budget.
    """
    length = lease.snapshot.byte_length
    if (
        type(start) is not int
        or start < 0
        or start % PAGE_BYTES != 0
        or not (start < length or start == length == 0)
    ):
        return failure(ErrorCode.INVALID_SELECTOR)
    return Success(
        memoryview(lease.verified_bytes)[start : min(start + PAGE_BYTES, length)]
    )
