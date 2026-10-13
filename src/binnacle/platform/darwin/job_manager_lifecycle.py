"""Darwin manager owner acknowledgements after guarded, durable transitions.

The owner, not a peer or on-disk record, is the only signal authority. Moving
these small wrappers out of the service preserves the strict source line budget.
"""

from __future__ import annotations

import logging
from typing import Literal, Protocol

from binnacle.platform.contracts import process_contracts as pc


class LifecycleOwner(Protocol):
    """Only an already-owned job may be signalled or released."""

    def release(self, job_id: str) -> None: ...

    def signal_owned_group(
        self, job_id: str, intent: Literal["terminate", "kill"]
    ) -> None: ...


def quiet_kill_owned(
    owner: LifecycleOwner, job_id: str, logger: logging.Logger
) -> None:
    """Refuse to signal unknown groups; never bypass the owner authority."""
    try:
        owner.signal_owned_group(job_id, "kill")
    except (pc.UnverifiedJobProcess, pc.JobSignalDeliveryError, OSError):
        logger.warning("event=job_start_cleanup_unverified job_id=%s", job_id)


def release_owned_exit(
    owner: LifecycleOwner, job_id: str, logger: logging.Logger
) -> None:
    """Notify the in-memory owner only after durable terminal metadata exists."""
    try:
        owner.release(job_id)
    except (pc.UnverifiedJobProcess, ValueError, pc.JobOwnerLost):
        logger.warning("event=job_release_refused job_id=%s", job_id)
