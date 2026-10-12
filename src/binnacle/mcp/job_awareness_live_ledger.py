"""Production Job Awareness: in-memory, owner-scoped job bindings.

Each binding row is keyed by the route key ``kd`` (``epoch:d_subj:d_sess``,
HMAC digests from the core ``session_route`` keyer). A raw platform value is
never stored here. A job is bound only to the key of the ``run_command`` call
that returned it as a running background job. Every read and write names the
caller's own key, so no lookup can reach another conversation's rows; there
is no global job index (E2 design §2.3, owner scope first).

States: ``PENDING`` (bound, no hint yet), ``ACKED`` (the same conversation
read the job's terminal state, or stopped it), ``EMITTED`` (the one hint was
returned). Only ``PENDING`` rows are hint candidates, so a job is hinted at
most once (design §2.6, once-only).

Memory only. A restart builds a new keyer epoch and an empty ledger, so jobs
started before the restart are never hinted (fail closed). Caps bound memory:
``MAX_JOBS_PER_KEY`` rows per key (non-pending rows are dropped first; a key
full of pending rows refuses a new binding), ``MAX_KEYS`` keys (the least
recently used key is dropped), and ``TTL_S`` per row.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass

__all__ = [
    "ACKED",
    "EMITTED",
    "JOB_ID",
    "MAX_JOBS_PER_KEY",
    "MAX_KEYS",
    "PENDING",
    "TTL_S",
    "Ledger",
]

PENDING = "PENDING"
ACKED = "ACKED"
EMITTED = "EMITTED"
#: Binnacle job ids are 12 lowercase hex characters.
JOB_ID = re.compile(r"[0-9a-f]{12}")
MAX_JOBS_PER_KEY = 8
MAX_KEYS = 256
TTL_S = 24 * 3600.0


@dataclass
class _Row:
    bound_at: float
    state: str


def valid_job_id(value: object) -> bool:
    return type(value) is str and JOB_ID.fullmatch(value) is not None


class Ledger:
    """kd -> ordered job rows. Synchronous; callers hold the per-key fence."""

    def __init__(self) -> None:
        self._keys: OrderedDict[str, OrderedDict[str, _Row]] = OrderedDict()

    def _rows(self, kd: str, now: float) -> OrderedDict[str, _Row] | None:
        rows = self._keys.get(kd)
        if rows is None:
            return None
        for job_id in [j for j, row in rows.items() if now - row.bound_at > TTL_S]:
            del rows[job_id]
        if not rows:
            del self._keys[kd]
            return None
        self._keys.move_to_end(kd)
        return rows

    def bind(self, kd: str, job_id: str, now: float) -> str:
        """``bound``, ``duplicate``, ``key_full`` or ``invalid``."""
        if type(kd) is not str or not valid_job_id(job_id):
            return "invalid"
        rows = self._rows(kd, now)
        if rows is None:
            rows = self._keys[kd] = OrderedDict()
            while len(self._keys) > MAX_KEYS:
                self._keys.popitem(last=False)
        if job_id in rows:
            return "duplicate"
        if len(rows) >= MAX_JOBS_PER_KEY:
            done = [j for j, row in rows.items() if row.state != PENDING]
            if not done:
                return "key_full"
            del rows[done[0]]
        rows[job_id] = _Row(now, PENDING)
        return "bound"

    def state(self, kd: str, job_id: str, now: float) -> str | None:
        rows = self._rows(kd, now)
        row = None if rows is None else rows.get(job_id)
        return None if row is None else row.state

    def pending(self, kd: str, now: float) -> tuple[str, ...]:
        """The key's own pending job ids, oldest binding first."""
        rows = self._rows(kd, now)
        if rows is None:
            return ()
        return tuple(j for j, row in rows.items() if row.state == PENDING)

    def _set(self, kd: str, job_id: str, state: str, now: float) -> bool:
        rows = self._rows(kd, now)
        row = None if rows is None else rows.get(job_id)
        if row is None or row.state != PENDING:
            return False
        row.state = state
        return True

    def ack(self, kd: str, job_id: str, now: float) -> bool:
        """The conversation saw the job's end; True when a pending row changed."""
        return self._set(kd, job_id, ACKED, now)

    def emitted(self, kd: str, job_ids: tuple[str, ...], now: float) -> bool:
        """Mark every job emitted; False (nothing changed) if one is not pending."""
        if not all(self.state(kd, j, now) == PENDING for j in job_ids):
            return False
        return all(self._set(kd, j, EMITTED, now) for j in job_ids)

    def forget(self, kd: str, job_id: str, now: float) -> None:
        """Drop a row whose job no longer exists in the job store."""
        rows = self._rows(kd, now)
        if rows is not None:
            rows.pop(job_id, None)
            if not rows:
                del self._keys[kd]

    def __len__(self) -> int:
        return sum(len(rows) for rows in self._keys.values())
