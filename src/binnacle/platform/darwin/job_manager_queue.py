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


class ExitQueueStorage:
    owner: LifecycleOwner
    _queue_lock: threading.Lock
    _unrecorded: dict[str, OwnedJobExit]
    _unrecorded_since: dict[str, float]
    _acknowledged_exits: OrderedDict[str, None]
    _active_attempts: dict[str, int]
    _ack_pending: set[str]

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

    def _process_reaped_batch(
        self,
        exits: Sequence[OwnedJobExit],
        record: Callable[[OwnedJobExit, float], bool | None],
        wait_s: float,
    ) -> None:
        """Pin reaper callbacks until their queue/write choice has completed."""
        log = logging.getLogger("binnacle.job_manager")
        with self._queue_lock:
            for exited in exits:
                job_id = exited.job_id
                self._active_attempts[job_id] = self._active_attempts.get(job_id, 0) + 1
        try:
            busy = False
            for exited in exits:
                if busy:
                    self._queue(exited)
                    log.warning(
                        "event=job_exit_unrecorded job_id=%s reason=busy",
                        exited.job_id,
                    )
                else:
                    busy = record(exited, wait_s) is None
        finally:
            with self._queue_lock:
                for exited in exits:
                    job_id = exited.job_id
                    remaining = self._active_attempts[job_id] - 1
                    if remaining:
                        self._active_attempts[job_id] = remaining
                    else:
                        del self._active_attempts[job_id]
                self._trim_acked_locked()

    def _ack_later(self, job_id: str) -> None:
        with self._queue_lock:
            self._ack_pending.add(job_id)

    def _ack_complete(self, job_id: str) -> None:
        with self._queue_lock:
            self._ack_pending.discard(job_id)

    def _ack_snapshot(self) -> tuple[str, ...]:
        with self._queue_lock:
            return tuple(self._ack_pending)

    def _needs_retry(self) -> bool:
        with self._queue_lock:
            return bool(self._unrecorded or self._ack_pending)

    def _ack_owner(self, job_id: str) -> None:
        log = logging.getLogger("binnacle.job_manager")
        try:
            release_owned_exit(self.owner, job_id, log)
        except Exception as exc:  # noqa: BLE001 - the terminal fsync is committed
            self._ack_later(job_id)
            log.warning(
                "event=job_release_retry job_id=%s error_class=%s",
                job_id,
                type(exc).__name__,
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
