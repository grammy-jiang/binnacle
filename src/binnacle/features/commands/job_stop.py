"""Platform-independent durable-job stop policy with an opaque signal lease.

The backend validates and pins native process targets before Core can request
signals. The lease lives across TERM -> bounded wait -> KILL, so a disappearing
leader cannot redirect escalation to a reused process identifier.
"""

import logging
from collections.abc import Callable

from binnacle.platform.contracts.process_contracts import (
    ProcessBackend,
    UnverifiedJobProcess,
)


def stop_embedded(
    job_id: str,
    *,
    process_backend: ProcessBackend,
    job_state: Callable[[str], dict | None],
    read_meta: Callable[[str], dict | None],
    await_exit: Callable[[str, float], dict | None],
    stop_sigterm_grace_s: float,
    stop_sigkill_grace_s: float,
    current_call_id: Callable[[], str],
    logger: logging.Logger,
) -> dict | None:
    """Never issue a signal without an owner-verified native process identity."""
    state = job_state(job_id)
    if state is None:
        return None
    if state["state"] != "running":
        if state["state"] == "unknown":
            meta = read_meta(job_id)
            if meta is not None and meta.get("stop_requested"):
                return await_exit(job_id, stop_sigkill_grace_s)
        return state

    meta = read_meta(job_id)
    identity = process_backend.identity_from_record(meta or {})
    if identity is None:
        logger.warning(
            "event=job_stop_unverified job_id=%s reason=missing_identity", job_id
        )
        return state

    try:
        lease = process_backend.open_job_signals(identity)
    except (UnverifiedJobProcess, ProcessLookupError) as exc:
        logger.warning(
            "event=job_stop_unverified job_id=%s reason=%s",
            job_id,
            type(exc).__name__,
        )
        return job_state(job_id)

    try:
        try:
            lease.signal("terminate")
        except ProcessLookupError:
            return await_exit(job_id, stop_sigkill_grace_s)

        # Wait for the reaper's durable status, not merely for PID disappearance.
        settled = await_exit(job_id, stop_sigterm_grace_s)
        if settled is None or settled["state"] == "exited":
            return settled
        logger.warning(
            "event=job_stop_escalate job_id=%s call=%s signal=SIGKILL grace_s=%s",
            job_id,
            current_call_id(),
            stop_sigterm_grace_s,
        )
        try:
            lease.signal("kill")
        except ProcessLookupError:
            pass
        return await_exit(job_id, stop_sigkill_grace_s)
    finally:
        lease.close()
