"""Pending Darwin exit queue storage, separate from the durable record writer.

Never treats a queued exit as durable or authoritative. Thread-safe metadata
serves observability only; caller keeps all actual persistence and retry logic.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager

from binnacle.platform.contracts.process_contracts import OwnedJobExit
from binnacle.platform.darwin.job_manager_lifecycle import (
    LifecycleOwner,
    release_owned_exit,
)

# Bounded recent commit history plus pins for writers still in flight.
# A paused timed-out writer must not resurrect its job after thousands of
# other commits. Pins are proportional to concurrent calls, not lifetime jobs.
ACK_HISTORY_LIMIT = 2048
ACK_BACKLOG_LIMIT = 1024
ACK_RETRY_BATCH = 16
ACK_BACKOFF_MAX_S = 30.0


class ExitQueueStorage:
    owner: LifecycleOwner
    _queue_lock: threading.Lock
    _unrecorded: dict[str, OwnedJobExit]
    _unrecorded_since: dict[str, float]
    _acknowledged_exits: OrderedDict[str, None]
    _active_attempts: dict[str, int]
    _ack_pending: set[str]
    _ack_failures: dict[str, int]
    _ack_due: dict[str, float]
    stopping: threading.Event

    def _queue(self, exited: OwnedJobExit) -> None:
        with self._queue_lock:
            if exited.job_id in self._acknowledged_exits:
                return  # a late timed-out writer cannot resurrect a durable exit
            self._unrecorded[exited.job_id] = exited
            self._unrecorded_since.setdefault(exited.job_id, time.monotonic())

    def _dequeue(self, job_id: str, *, committed: bool = False) -> None:
        with self._queue_lock:
            self._unrecorded.pop(job_id, None)
            self._unrecorded_since.pop(job_id, None)
            if committed:
                self._acknowledged_exits[job_id] = None
                self._acknowledged_exits.move_to_end(job_id)
                self._trim_acked_locked()

    def _trim_acked_locked(self) -> None:
        # Do not copy 2k IDs on every completion. Active writers pin a marker;
        # older unpinned entries are reclaimed in amortized constant time.
        examined = len(self._acknowledged_exits)
        while len(self._acknowledged_exits) > ACK_HISTORY_LIMIT and examined:
            oldest = next(iter(self._acknowledged_exits))
            if oldest in self._active_attempts:
                self._acknowledged_exits.move_to_end(oldest)
            else:
                self._acknowledged_exits.popitem(last=False)
            examined -= 1

    @contextmanager
    def _pinned_batch(
        self, exits: Sequence[OwnedJobExit] | None = None
    ) -> Iterator[tuple[OwnedJobExit, ...]]:
        """Snapshot the queue and pin EVERY writer in one mutex section."""
        with self._queue_lock:
            chosen = tuple(self._unrecorded.values()) if exits is None else tuple(exits)
            for exited in chosen:
                name = exited.job_id
                self._active_attempts[name] = self._active_attempts.get(name, 0) + 1
        try:
            yield chosen
        finally:
            with self._queue_lock:
                for exited in chosen:
                    name = exited.job_id
                    left = self._active_attempts[name] - 1
                    if left:
                        self._active_attempts[name] = left
                    else:
                        del self._active_attempts[name]
                self._trim_acked_locked()

    def _process_reaped_batch(
        self,
        exits: Sequence[OwnedJobExit],
        record: Callable[[OwnedJobExit, float], bool | None],
        wait_s: float,
    ) -> None:
        """Pin reaper callbacks until their queue/write choice has completed."""
        log = logging.getLogger("binnacle.job_manager")
        with self._pinned_batch(exits) as pinned:
            busy = False
            for exited in pinned:
                if busy:
                    self._queue(exited)
                    log.warning(
                        "event=job_exit_unrecorded job_id=%s reason=busy",
                        exited.job_id,
                    )
                else:
                    busy = record(exited, wait_s) is None

    def _ack_later(self, job_id: str) -> int:
        """Schedule bounded owner acknowledgement; stop if backpressure fills.

        Terminal metadata and job_exit were already committed. Overflow must
        stop this manager rather than drop the durable owner responsibility
        invisibly or grow indefinitely.
        """
        overflow = False
        with self._queue_lock:
            if job_id not in self._ack_pending:
                if len(self._ack_pending) >= ACK_BACKLOG_LIMIT:
                    overflow = True
                else:
                    self._ack_pending.add(job_id)
            if not overflow:
                count = self._ack_failures.get(job_id, 0) + 1
                self._ack_failures[job_id] = count
                backoff = min(ACK_BACKOFF_MAX_S, 0.5 * (2 ** min(8, count - 2)))
                self._ack_due[job_id] = time.monotonic() + (
                    0 if count == 1 else backoff
                )
        if overflow:
            if not self.stopping.is_set():
                self.stopping.set()
                logging.getLogger("binnacle.job_manager").error(
                    "event=job_release_backlog_exceeded pending=%d action=stop",
                    ACK_BACKLOG_LIMIT,
                )
            return 0
        return count

    def _ack_complete(self, job_id: str) -> None:
        with self._queue_lock:
            self._ack_pending.discard(job_id)
            self._ack_failures.pop(job_id, None)
            self._ack_due.pop(job_id, None)

    def _ack_snapshot(self) -> tuple[str, ...]:
        now = time.monotonic()
        with self._queue_lock:
            due = (
                job_id
                for job_id in sorted(self._ack_pending)
                if self._ack_due[job_id] <= now
            )
            return tuple(
                job_id for _, job_id in zip(range(ACK_RETRY_BATCH), due, strict=False)
            )

    def _needs_retry(self) -> bool:
        with self._queue_lock:
            return bool(self._unrecorded or self._ack_pending)

    def _ack_owner(self, job_id: str) -> None:
        log = logging.getLogger("binnacle.job_manager")
        try:
            release_owned_exit(self.owner, job_id, log)
        except Exception as exc:  # noqa: BLE001 - the terminal fsync is committed
            failures = self._ack_later(job_id)
            # Exponential warning cadence prevents an unreachable owner from
            # emitting unbounded reaper log volume while the retry slows down.
            if failures and not failures & (failures - 1):
                log.warning(
                    "event=job_release_retry job_id=%s error_class=%s attempt=%d",
                    job_id,
                    type(exc).__name__,
                    failures,
                )
        else:
            self._ack_complete(job_id)

    def _retry_acks(self) -> None:
        for job_id in self._ack_snapshot():
            self._ack_owner(job_id)

    def _is_queued(self, job_id: str) -> bool:
        """Read pending receipt state under the same queue mutex as updates."""
        with self._queue_lock:
            return job_id in self._unrecorded

    @contextmanager
    def _pin_exit_callback(self, job_id: str) -> Iterator[None]:
        """Keep the completion marker alive until a callback can no longer queue."""
        with self._queue_lock:
            self._active_attempts[job_id] = self._active_attempts.get(job_id, 0) + 1
        try:
            yield
        finally:
            with self._queue_lock:
                remaining = self._active_attempts[job_id] - 1
                if remaining:
                    self._active_attempts[job_id] = remaining
                else:
                    del self._active_attempts[job_id]
                self._trim_acked_locked()

    @contextmanager
    def _persist_or_queue(
        self,
        exited: OwnedJobExit,
        transaction: AbstractContextManager[None],
    ) -> Iterator[None]:
        """Mark I/O failures before releasing the writer transaction.

        An earlier replace may already expose terminal JSON. A concurrent
        retry must never mistake that visibility for a completed directory
        fsync. If lock acquisition fails before entering, queue afterward.
        Never requeue outside the lock if a concurrent retry completed.
        """
        queued_inside = False
        with self._pin_exit_callback(exited.job_id):
            try:
                with transaction:
                    try:
                        yield
                    except OSError:
                        self._queue(exited)
                        queued_inside = True
                        raise
            except OSError:
                if not queued_inside:
                    self._queue(exited)
                raise
