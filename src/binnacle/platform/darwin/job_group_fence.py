"""SD-43 leader-exit fence for ``DarwinJobProcessOwner`` (split for module size).

JCRP-F1 (Linux parity): a leader exit is read with waitid(WNOWAIT) and
reported once, while the zombie leader stays unreaped as the pgid fence for
background members still in its group (public sysctl KERN_PROC_PGRP). It is
reaped once no non-zombie member remains, or by close(). Like Linux, a stop
after the leader exit signals nothing. JCRP-F3: a failed read-only observation
is transient (lost after ``OBSERVATION_FAILURE_LIMIT``); JCRP-F5: the guarded
killpg is the only group signal; JCRP-N7: ``_released`` is bounded.
"""

from __future__ import annotations

import errno
import os
from threading import Condition
from typing import Literal

from binnacle.platform.contracts.process_contracts import (
    JobSignalDeliveryError,
    OwnedJobExit,
    UnverifiedJobProcess,
)
from binnacle.platform.darwin.process_authority import (
    _OwnedLeaderWait,
    _process_records,
    _ProcessRecord,
)
from binnacle.platform.darwin.process_backend import _OwnedExitTable, _OwnedJob

# JCRP-F3: a failed read-only observation is transient; lost only after this
# many consecutive failures (proven ECHILD or birth mismatch: at once).
OBSERVATION_FAILURE_LIMIT = 3
# JCRP-N7: released ids kept for the duplicate-writer check, oldest dropped
# first; the durable spool record is the lasting guard.
RELEASED_LIMIT = 1024
_SZOMB = 5

TerminationReason = Literal["normal_exit", "signal", "stop_requested", "owner_restart"]


class _GroupFence(_OwnedExitTable):
    """Fence, observation and release state shared with the owner (one lock)."""

    _changed: Condition
    _acked: set[str]  # released while the group is fenced
    _failures: dict[str, int]  # consecutive observation failures
    _lost_unreported: list[str]  # lost jobs the manager must persist
    _fault: str | None

    def _child_record(self, pid: int) -> _ProcessRecord | None:
        raise NotImplementedError

    def _child_record_or_raise(self, pid: int) -> _ProcessRecord | None:
        raise NotImplementedError

    def _reap_locked(self, job: _OwnedJob) -> OwnedJobExit | None:
        """Capture the leader exit (WNOWAIT); reap only an empty group (F1).

        Returns the exit once, when first captured. The zombie leader keeps
        the pgid while a live member remains: no signal is sent here (F5).
        """
        if self._observe_locked(job) is None:
            return None
        captured = None
        if job.exit is None:
            captured = self._capture_exit_locked(job)
            if captured is None:
                return None
        try:
            members = _process_records(2, job.pid)
        except OSError:
            return captured  # transient: the fence holds, retried next tick
        if any(m.pid != job.pid and m.state != _SZOMB for m in members):
            return captured  # background members live: keep the fence (Linux)
        self._reap_leader_locked(job)
        return captured

    def _capture_exit_locked(self, job: _OwnedJob) -> OwnedJobExit | None:
        flags = os.WEXITED | os.WNOHANG | os.WNOWAIT
        try:
            # typeshed omits Darwin's waitid(2); CPython provides it there.
            info = getattr(os, "waitid")(os.P_PID, job.pid, flags)  # noqa: B009
        except ChildProcessError:
            # ECHILD: another waiter reaped our child. Never claim an exit.
            self._mark_lost_locked(job, "darwin_exclusive_reaper_required")
            return None
        except OSError:
            return None  # transient; the zombie keeps it pending
        if info is None or info.si_pid != job.pid:
            return None
        if info.si_code == os.CLD_EXITED:
            code, number = info.si_status, None
        elif info.si_code in (os.CLD_KILLED, os.CLD_DUMPED):
            code, number = None, info.si_status
        else:
            return None  # stopped/continued is not an exit
        reason: TerminationReason = "normal_exit"
        if job.close_signalled:  # running when the owner stop began (RJ1-F8)
            reason = "owner_restart"
        elif job.stop_requested:  # same order as Linux jobs._termination_reason
            reason = "stop_requested"
        elif number is not None:
            reason = "signal"
        job.exit = OwnedJobExit(job.job_id, code, number, reason)
        job.reason_code = "darwin_job_leader_exited"
        return job.exit

    def _reap_leader_locked(self, job: _OwnedJob) -> None:
        """wait4 the zombie leader: the sole reap site; closes the fence."""
        try:
            waited, status = _OwnedLeaderWait(job.pid).wait4()
        except ChildProcessError:
            self._mark_lost_locked(job, "darwin_exclusive_reaper_required")
            return
        except OSError:
            self._mark_lost_locked(job, "darwin_job_reap_unverified")
            return
        if not waited:
            return
        job.reaped = True
        if waited != job.pid or not (os.WIFEXITED(status) or os.WIFSIGNALED(status)):
            self._mark_lost_locked(job, "darwin_job_reap_unverified")
            return
        job.reason_code = "darwin_job_reaped"
        if job.job_id in self._acked:
            self._acked.discard(job.job_id)
            self._move_released_locked(job)

    def _mark_lost_locked(self, job: _OwnedJob, code: str) -> None:
        if not job.lost and job.exit is None:
            self._lost_unreported.append(job.job_id)  # F3: the spool says UNKNOWN
        job.lost = True
        job.reason_code = code
        self._failures.pop(job.job_id, None)
        self._changed.notify_all()

    def _observe_locked(self, job: _OwnedJob) -> _ProcessRecord | None:
        """Our same-birth child, else None.

        A proven absence or birth mismatch marks the job lost (another waiter
        reaped it; never adopt). A failed sysctl read is transient (JCRP-F3):
        lost only after ``OBSERVATION_FAILURE_LIMIT`` consecutive failures.
        """
        try:
            record = self._child_record_or_raise(job.pid)
        except OSError:
            count = self._failures.get(job.job_id, 0) + 1
            self._failures[job.job_id] = count
            if count >= OBSERVATION_FAILURE_LIMIT:
                self._mark_lost_locked(job, "darwin_job_observation_failed")
            return None
        self._failures.pop(job.job_id, None)
        if record is None or record.birth != job.birth:
            self._mark_lost_locked(job, "darwin_exclusive_reaper_required")
            return None
        return record

    def take_lost(self) -> list[str]:
        """Jobs lost without an exit since the last call (manager persists D-1)."""
        self._check_owner()
        with self._lock:
            lost, self._lost_unreported = self._lost_unreported, []
            return lost

    def processes(self, job_id: str, max_cmd_chars: int = 200) -> list[dict]:
        """JCRP-F6: read-only KERN_PROC_PGRP listing of an owned, fenced group."""
        from binnacle.platform.darwin.job_manager_entry import group_listing

        self._check_owner()
        with self._lock:
            job = self._lookup_locked(job_id)
            if job is None or job.reaped or job.lost or self._fault is not None:
                return []
            record = self._observe_locked(job)
            if record is None or record.group != job.pid:
                return []
            return group_listing(job.pid, max_cmd_chars)

    def _killpg_guarded_locked(
        self, job: _OwnedJob, record: _ProcessRecord, number: int
    ) -> None:
        """The only killpg site (RJ1-F11/JCRP-F5): group == pid != getpgrp()."""
        # setsid at spawn: the group is the leader's pid. Never redirect a
        # signal to a group the leader moved to, nor to the manager's own.
        if record.group != job.pid or record.group == os.getpgrp():
            self._mark_lost_locked(job, "darwin_job_group_unverified")
            raise UnverifiedJobProcess(job.reason_code)
        try:
            os.killpg(job.pid, number)
        except ProcessLookupError:
            # Only the unreaped zombie leader is left: nothing to deliver. It
            # may have exited after the read above (RJ1-F7): read it again.
            record = self._child_record(job.pid) or record
            if record.state != _SZOMB or record.birth != job.birth:
                raise JobSignalDeliveryError("darwin_job_signal_partial") from None
        except OSError as exc:
            partial = exc.errno == errno.EPERM
            raise JobSignalDeliveryError(
                "darwin_job_signal_partial" if partial else "darwin_job_signal_failed"
            ) from None

    def release(self, job_id: str) -> None:
        """Ack a durable terminal record; a fenced group stays in the scans."""
        self._check_owner()
        with self._lock:
            job = self._jobs.get(job_id)
            fenced = job is not None and job.exit is not None
            if fenced and job is not None and not job.reaped and not job.lost:
                self._acked.add(job_id)  # moved once the leader is reaped
                return
        super().release(job_id)
        with self._lock:
            self._trim_released_locked()

    def _move_released_locked(self, job: _OwnedJob) -> None:
        self._jobs.pop(job.job_id, None)
        if self._by_pid.get(job.pid) is job:
            del self._by_pid[job.pid]
        self._released[job.job_id] = job
        self._trim_released_locked()

    def _trim_released_locked(self) -> None:
        while len(self._released) > RELEASED_LIMIT:  # JCRP-N7: oldest first
            del self._released[next(iter(self._released))]
