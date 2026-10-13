"""Pending Darwin exit queue storage, separate from the durable record writer.

Never treats a queued exit as durable or authoritative. Thread-safe metadata
serves observability only; caller keeps all actual persistence and retry logic.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager

from binnacle.platform.contracts.process_contracts import OwnedJobExit


class ExitQueueStorage:
    _queue_lock: threading.Lock
    _unrecorded: dict[str, OwnedJobExit]
    _unrecorded_since: dict[str, float]
    _acknowledged_exits: set[str]

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
                self._acknowledged_exits.add(job_id)

    def _is_queued(self, job_id: str) -> bool:
        """Read pending receipt state under the same queue mutex as updates."""
        with self._queue_lock:
            return job_id in self._unrecorded

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
