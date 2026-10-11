"""Stopping and loss-persistence helpers of ``DarwinJobManager`` (SD-43 split).

JCRP-F2: ``stopping`` (shared with serve_job_manager's stop event, so SIGTERM
sets it) releases every waiting handler at once: a start returns its job id
auto-backgrounded, a stop its current state; close() then owns the stop.
JCRP-F3: owner-proven losses become durable authority UNKNOWN (D-1).
JCRP-F6: the additive read-only ``processes`` op (Linux: running jobs only).
R-M1-N1: ``hold_jobs_dir``, the jobs dir whose writer lock this manager holds.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections.abc import Mapping
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Literal

from binnacle.platform.contracts import process_contracts as pc
from binnacle.platform.contracts.process_contracts import OwnedJobExit

log = logging.getLogger("binnacle.job_manager")
Partial, Unowned = pc.JobSignalDeliveryError, pc.UnverifiedJobProcess
_JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_STOP_PHASES: tuple[Literal["terminate", "kill"], ...] = ("terminate", "kill")
# JCRP-F2: waiting handlers re-check ``stopping`` at least this often, so a
# SIGTERM never waits for a run_command wait window (<= wait_max_s).
STOPPING_SLICE_S = 0.1


def _terminal(meta: Mapping[str, object]) -> bool:
    return "exit_code" in meta or "signal" in meta


class _ManagerStopping:
    """Mixed into ``DarwinJobManager``; the stubs below are its own methods."""

    owner: pc.DarwinJobOwner
    owner_instance_id: str
    grace: tuple[float, float]
    stopping: threading.Event
    jobs_dir: Path
    held_jobs_dir: str | None

    def _transaction(self) -> AbstractContextManager[None]:
        raise NotImplementedError

    def _meta(self, job_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def _write_meta(self, job_id: str, meta: Mapping[str, object]) -> None:
        raise NotImplementedError

    def _mark_unknown(self, job_id: str, meta: dict[str, Any], reason: str) -> None:
        raise NotImplementedError

    def _release(self, job_id: str) -> None:
        raise NotImplementedError

    def _persist_partial(self, job_id: str) -> None:
        raise NotImplementedError

    def record_exit(self, exited: OwnedJobExit) -> bool:
        raise NotImplementedError

    def state(self, job_id: str) -> str:
        raise NotImplementedError

    def hold_jobs_dir(self, lock_fd: int) -> str:
        """R-M1-N1: the realpath is the jobs dir only if it names the locked inode.

        ``lock_fd`` is this manager's ``<jobs_dir>/.manager.lock`` with the
        writer flock held. A symlinked jobs dir retargeted between the lock and
        the realpath names a dir this manager does not hold: fail closed, before
        recovery and binding. ``lstat``: a linked lock file is never ours.
        """
        held = os.path.realpath(self.jobs_dir)
        locked = os.fstat(lock_fd)
        try:
            named = os.lstat(os.path.join(held, ".manager.lock"))
        except OSError:
            named = None
        identity = (locked.st_dev, locked.st_ino)
        if named is None or (named.st_dev, named.st_ino) != identity:
            event = "event=job_manager_jobs_dir_mismatch jobs_dir=%s realpath=%s"
            log.error(event, self.jobs_dir, held)
            raise RuntimeError("job_manager_jobs_dir_mismatch")
        self.held_jobs_dir = held
        return held

    def _wait_exit(self, job_id: str, seconds: float) -> OwnedJobExit | None:
        """owner.wait in short slices; returns None early once ``stopping``."""
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            remaining = deadline - time.monotonic()
            exited = self.owner.wait(job_id, max(0.0, min(remaining, STOPPING_SLICE_S)))
            if exited is not None or remaining <= STOPPING_SLICE_S:
                return exited
            if self.stopping.is_set():
                return None

    def _stop_owned(self, job_id: str, call_id: str) -> str:
        """A1 order: durable prepare -> TERM -> grace -> KILL -> reaper evidence."""
        with self._transaction():
            meta = self._meta(job_id)
            if meta is not None and not _terminal(meta):
                meta.update(stop_requested=True, stop_call_id=call_id)
                self._write_meta(job_id, meta)
        partial: list[Exception] = []
        for intent, grace in zip(_STOP_PHASES, self.grace, strict=True):
            if self.stopping.is_set():
                break  # F2: close() owns the stop now; report the current state
            try:
                self.owner.signal_owned_group(job_id, intent)
            except Unowned:
                break  # leader reaped (pgid may recycle) or not ours: no signal
            except Partial as exc:
                partial.append(exc)
                self._persist_partial(job_id)
            try:
                exited = self._wait_exit(job_id, grace)
            except pc.JobOwnerLost:
                log.warning("event=job_stop_owner_lost job_id=%s", job_id)
                break  # authority UNKNOWN: record no exit, signal nothing more
            if exited is not None:
                self.record_exit(exited)
                break
        deadline = time.monotonic() + self.grace[1]
        while (state := self.state(job_id)) != "exited" and time.monotonic() < deadline:
            if self.stopping.is_set():
                break
            time.sleep(0.02)
        if partial:
            raise Partial("; ".join(str(item) for item in partial))
        return state

    def _processes(self, request: dict[str, Any]) -> dict[str, Any]:
        """JCRP-F6: read-only group listing for this incarnation's running job."""
        job_id = request["job_id"]
        max_cmd_chars = int(request.get("max_cmd_chars", 200))
        if not isinstance(job_id, str) or not 1 <= max_cmd_chars <= 4096:
            raise ValueError("processes request has invalid fields")
        listing = getattr(self.owner, "processes", None)
        if not _JOB_ID.fullmatch(job_id) or listing is None:
            return {"ok": True, "job_id": job_id, "processes": []}
        if self.state(job_id) != "running":
            return {
                "ok": True,
                "job_id": job_id,
                "processes": [],
            }  # Linux: running only
        return {
            "ok": True,
            "job_id": job_id,
            "processes": listing(job_id, max_cmd_chars),
        }

    def persist_lost(self) -> int:
        """JCRP-F3: owner-proven losses -> durable authority UNKNOWN (D-1)."""
        take = getattr(self.owner, "take_lost", None)
        lost = list(take()) if take is not None else []
        for job_id in lost:
            try:
                with self._transaction():
                    meta = self._meta(job_id)
                    if (
                        meta is None
                        or meta.get("owner_instance_id") != self.owner_instance_id
                    ):
                        continue
                    if not _terminal(meta):
                        self._mark_unknown(job_id, meta, "owner_restart")
            except OSError:
                log.warning("event=job_lost_unrecorded job_id=%s", job_id)
                continue  # close() still marks it UNKNOWN
            self._release(job_id)
        return len(lost)
