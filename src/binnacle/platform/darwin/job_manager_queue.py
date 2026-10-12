"""Pending Darwin exit queue storage, separate from the durable record writer.

Never treats a queued exit as durable or authoritative. Thread-safe metadata
serves observability only; caller keeps all actual persistence and retry logic.
"""

from __future__ import annotations

import threading
import time

from binnacle.platform.contracts.process_contracts import OwnedJobExit


class ExitQueueStorage:
    _queue_lock: threading.Lock
    _unrecorded: dict[str, OwnedJobExit]
    _unrecorded_since: dict[str, float]

    def _queue(self, exited: OwnedJobExit) -> None:
        with self._queue_lock:
            self._unrecorded[exited.job_id] = exited
            self._unrecorded_since.setdefault(exited.job_id, time.monotonic())

    def _dequeue(self, job_id: str) -> None:
        with self._queue_lock:
            self._unrecorded.pop(job_id, None)
            self._unrecorded_since.pop(job_id, None)
