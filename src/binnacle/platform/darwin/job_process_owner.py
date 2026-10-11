"""Darwin durable-job process owner (interface 1.2.0 ``DarwinJobOwner``).

One instance per stable-manager incarnation. Leaders are posix_spawn(setsid)
session leaders (``pgid == pid``); the kqueue NOTE_EXIT watch is armed before
spawn returns (ESRCH: exit pending). ``reap_exits`` is the sole waitpid caller
(SIGCHLD stays SIG_DFL), driven by one reaper thread; ``wait`` only waits on
its condition. Authority is the in-memory (pid, birth) table only, never
adopted; a reaped leader closes the signal fence; ECHILD/ESRCH -> UNKNOWN.
Descendants leaving the group are not tracked: descendants_unverified=true.
"""

from __future__ import annotations

import errno
import os
import select
import signal
import sys
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from threading import Condition, RLock, Thread
from typing import BinaryIO, Literal
from uuid import uuid4

from binnacle.platform.contracts.process_contracts import (
    JobOwnerLost,
    JobSignalDeliveryError,
    OwnedJobExit,
    OwnedJobObservation,
    OwnedJobProcess,
    UnverifiedJobProcess,
)
from binnacle.platform.darwin.process_authority import (
    _is_darwin,
    _OwnedLeaderWait,
    _process_records,
    _process_token,
    _ProcessRecord,
    _unavailable,
    _unknown,
    _validate_process_layout,
    birth_token,
)
from binnacle.platform.darwin.process_backend import _OwnedExitTable, _OwnedJob

# The Linux stop protocol constants (features/commands/jobs.py); a test pins them.
STOP_SIGTERM_GRACE_S = 5.0
STOP_SIGKILL_GRACE_S = 2.0
_REAPER_POLL_S = 0.05  # bounds how late close() and straggler deadlines are seen
# Every catchable signal starts SIG_DFL (Linux restores PIPE/XFZ/XFSZ).
_DEFAULT_SIGNALS = tuple(signal.valid_signals() - {signal.SIGKILL, signal.SIGSTOP})
# posix_spawn has no cwd: a POSIX sh shim changes directory, disables core
# dumps (design §5) and execs the formed argv, so the leader keeps its pid.
_SPAWN_SHIM = 'ulimit -c 0 2>/dev/null; cd -- "$1" || exit 126; shift; exec "$@"'

TerminationReason = Literal["normal_exit", "signal", "stop_requested", "owner_restart"]


class DarwinJobProcessOwner(_OwnedExitTable):
    """The sole owner, signaller and reaper of this incarnation's job leaders."""

    def __init__(
        self,
        *,
        boot_id: str,
        stop_sigterm_grace_s: float = STOP_SIGTERM_GRACE_S,
        stop_sigkill_grace_s: float = STOP_SIGKILL_GRACE_S,
        start_reaper: bool = True,
    ) -> None:
        if not _is_darwin():
            raise _unavailable("native_capability_unavailable")
        if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
            raise _unknown("darwin_exclusive_reaper_required")
        if not boot_id:
            raise _unknown("darwin_boot_identity_unavailable")
        _validate_process_layout()
        self._owner_pid = os.getpid()
        self._owner_token = _process_token()
        self._instance_id = uuid4().hex
        self._boot_id = boot_id
        self._graces = (
            (signal.SIGTERM, stop_sigterm_grace_s),
            (signal.SIGKILL, stop_sigkill_grace_s),
        )
        self._lock = RLock()
        self._changed = Condition(self._lock)
        self._jobs: dict[str, _OwnedJob] = {}
        self._by_pid: dict[int, _OwnedJob] = {}
        self._released: dict[str, _OwnedJob] = {}
        self._fault: str | None = None  # reaping failed: unreaped jobs UNKNOWN
        self._closing = False
        self._closed = False
        self._reaper: Thread | None = None
        if sys.platform == "darwin":
            self._queue: select.kqueue | None = select.kqueue()
        if start_reaper:
            self._reaper = Thread(
                target=self._reaper_loop, name="binnacle-job-reaper", daemon=True
            )
            self._reaper.start()

    @property
    def owner_instance_id(self) -> str:
        return self._instance_id

    @property
    def reaper_running(self) -> bool:
        return self._reaper is not None and self._reaper.is_alive()

    def _check_owner(self) -> None:
        # Before any lock: a forked child may inherit it locked. A fork never
        # inherits authority, even if it later holds a recycled numeric pid.
        if os.getpid() != self._owner_pid or self._owner_token is not _process_token():
            raise JobOwnerLost("darwin_job_owner_lost")

    def spawn(
        self,
        job_id: str,
        argv: Sequence[str],
        *,
        workdir: Path,
        env: Mapping[str, str],
        stdin: BinaryIO,
        output: BinaryIO,
    ) -> OwnedJobProcess:
        self._check_owner()
        if not argv:
            raise ValueError("argv must not be empty")
        with self._lock:
            if self._closing:
                raise _unavailable("darwin_job_owner_closing")
            if self._fault is not None:  # nothing would reap a new leader
                raise _unknown(self._fault)
            if self._lookup_locked(job_id) is not None:
                # No duplicate writer: one leader per job id per incarnation.
                raise ValueError("darwin_job_already_owned")
            if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
                raise _unknown("darwin_exclusive_reaper_required")
            out = output.fileno()
            pid = os.posix_spawn(
                "/bin/sh",
                ["/bin/sh", "-c", _SPAWN_SHIM, "binnacle-job", str(workdir), *argv],
                dict(env),
                file_actions=[
                    (os.POSIX_SPAWN_DUP2, stdin.fileno(), 0),
                    (os.POSIX_SPAWN_DUP2, out, 1),
                    (os.POSIX_SPAWN_DUP2, out, 2),
                ],
                setsid=True,
                setsigmask=(),
                setsigdef=_DEFAULT_SIGNALS,
            )
            try:
                record = self._child_record(pid)
                if record is None or record.group != pid:
                    raise _unknown("darwin_job_spawn_unverified", spawned=True)
                job = _OwnedJob(job_id, pid, record.birth)
                self._jobs[job_id] = self._by_pid[pid] = job
                self._arm_exit_watch_locked(job)
            except BaseException:
                # Our own fresh, unreaped spawn: its pid cannot have been
                # recycled, so killing and reaping it here is not adoption.
                self._jobs.pop(job_id, None)
                self._by_pid.pop(pid, None)
                with suppress(OSError):
                    os.kill(pid, signal.SIGKILL)
                    _OwnedLeaderWait(pid).wait4(block=True)
                raise
            self._changed.notify_all()
            return OwnedJobProcess(
                job_id=job_id,
                pid=pid,
                pgid=pid,
                birth=birth_token(record.birth),
                owner_instance_id=self._instance_id,
                boot_id=self._boot_id,
            )

    def _child_record(self, pid: int) -> _ProcessRecord | None:
        try:
            records = _process_records(1, pid)
        except OSError:
            return None
        if (
            len(records) != 1
            or records[0].pid != pid
            or records[0].parent != self._owner_pid
        ):
            return None
        return records[0]

    def _arm_exit_watch_locked(self, job: _OwnedJob) -> None:
        if sys.platform == "darwin":
            if self._queue is None:
                raise _unknown("darwin_job_owner_lost", spawned=True)
            change = select.kevent(
                job.pid,
                filter=select.KQ_FILTER_PROC,
                flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                fflags=select.KQ_NOTE_EXIT,
            )
            try:
                # max_events=0: a failed change raises instead of consuming
                # another job's pending NOTE_EXIT from the reaper.
                self._queue.control([change], 0, 0)
            except ProcessLookupError:
                # Under the exclusive-reaper contract this is our unreaped
                # zombie, not a reusable pid: the exit is already pending.
                job.exit_seen = True
            return
        raise _unavailable("native_capability_unavailable")

    def _reaper_loop(self) -> None:
        while True:
            with self._lock:
                if self._closed:
                    return
            try:
                self.reap_exits(_REAPER_POLL_S)
            except JobOwnerLost:
                return
            except OSError:
                # The loop head observes close(); never spin on a failing queue.
                time.sleep(_REAPER_POLL_S)
            except Exception:  # noqa: BLE001 - never die silently (RJ1-F2)
                self._record_fault()
                return

    def _record_fault(self) -> None:
        # Unreaped jobs -> UNKNOWN, waiters wake; close() still stops the groups.
        with self._lock:
            if not self._closed and self._fault is None:
                self._fault = "darwin_job_reaper_failed"
                self._changed.notify_all()

    def _poll_exit_events(self, timeout: float | None) -> list[int]:
        if sys.platform == "darwin":
            with self._lock:
                queue = self._queue
            if queue is None or queue.closed:
                return []
            return [
                event.ident
                for event in queue.control(None, 64, timeout)
                if event.filter == select.KQ_FILTER_PROC
                and event.fflags & select.KQ_NOTE_EXIT
                and not event.flags & select.KQ_EV_ERROR
            ]
        raise _unavailable("native_capability_unavailable")

    def reap_exits(self, timeout: float | None) -> Sequence[OwnedJobExit]:
        """kqueue NOTE_EXIT loop body: the sole waitpid(WNOHANG) caller."""
        self._check_owner()
        with self._lock:
            timeout = self._poll_timeout_locked(timeout)
        exited = self._poll_exit_events(timeout)
        with self._lock:
            for pid in exited:
                job = self._by_pid.get(pid)
                if job is not None and not job.reaped:
                    job.exit_seen = True
            results = []
            for job in tuple(self._jobs.values()):
                if job.exit_seen and not job.reaped and not job.lost:
                    result = self._reap_locked(job)
                    if result is not None:
                        results.append(result)
            if results or exited:
                self._changed.notify_all()
            return results

    def _poll_timeout_locked(self, timeout: float | None) -> float | None:
        # Exits awaiting a reap poll without blocking; straggler deadlines bound
        # the block so the leader is reaped on time, without spinning.
        now = time.monotonic()
        for job in self._jobs.values():
            if not job.exit_seen or job.reaped or job.lost:
                continue
            if job.straggler_deadline is None:
                return 0
            remaining = max(0.0, job.straggler_deadline - now)
            timeout = remaining if timeout is None else min(timeout, remaining)
        return timeout

    def _reap_locked(self, job: _OwnedJob) -> OwnedJobExit | None:
        """Reap an exited leader, whose zombie reserves the pgid until then.

        Group members are terminated first: a reap closes the signal fence."""
        if self._verified_record_locked(job) is None:
            return None
        try:
            members: list[_ProcessRecord] | None = _process_records(2, job.pid)
        except OSError:
            members = None
        if members is None or any(member.pid != job.pid for member in members):
            now = time.monotonic()
            if job.straggler_deadline is None:
                with suppress(OSError):
                    os.killpg(job.pid, signal.SIGTERM)
                job.straggler_deadline = now + self._graces[1][1]
                if not self._closing:
                    return None
            if not self._closing and now < job.straggler_deadline:
                return None
            with suppress(OSError):
                os.killpg(job.pid, signal.SIGKILL)
        try:
            waited, status = _OwnedLeaderWait(job.pid).wait4()
        except ChildProcessError:
            # ECHILD: another waiter reaped our child. Never claim an exit.
            self._mark_lost_locked(job, "darwin_exclusive_reaper_required")
            return None
        except OSError:
            self._mark_lost_locked(job, "darwin_job_reap_unverified")
            return None
        if not waited:
            return None
        job.reaped = True
        if waited != job.pid or not (os.WIFEXITED(status) or os.WIFSIGNALED(status)):
            self._mark_lost_locked(job, "darwin_job_reap_unverified")
            return None
        code = os.waitstatus_to_exitcode(status)
        reason: TerminationReason = "normal_exit"
        if job.close_signalled:  # running when the owner stop began (RJ1-F8)
            reason = "owner_restart"
        elif job.stop_requested:  # same order as Linux jobs._termination_reason
            reason = "stop_requested"
        elif code < 0:
            reason = "signal"
        job.exit = OwnedJobExit(
            job.job_id, code if code >= 0 else None, -code if code < 0 else None, reason
        )
        job.reason_code = "darwin_job_reaped"
        return job.exit

    def _mark_lost_locked(self, job: _OwnedJob, code: str) -> None:
        job.lost = True
        job.reason_code = code
        self._changed.notify_all()

    def _verified_record_locked(self, job: _OwnedJob) -> _ProcessRecord | None:
        """The unreaped leader must still be our child with the same birth.

        Absent while unreaped (ESRCH), reparented or reborn: another waiter
        reaped it. Never adopt a successor holding the numeric pid.
        """
        record = self._child_record(job.pid)
        if record is None or record.birth != job.birth:
            self._mark_lost_locked(job, "darwin_exclusive_reaper_required")
            return None
        return record

    def wait(self, job_id: str, timeout: float | None) -> OwnedJobExit | None:
        """Wait on the reaper's condition; None means still running at timeout."""
        self._check_owner()
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._lock:
            while True:
                job = self._lookup_locked(job_id)
                if job is None:
                    raise UnverifiedJobProcess("darwin_job_not_owned")
                if job.exit is not None:
                    return job.exit
                if job.lost:
                    raise JobOwnerLost(job.reason_code)
                if self._fault is not None:
                    raise JobOwnerLost(self._fault)
                if self._closed:
                    raise JobOwnerLost("darwin_job_owner_closed")
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return None
                self._changed.wait(remaining)

    def authority(self, job_id: str) -> OwnedJobObservation:
        def unknown(code: str, alive: bool | None = None) -> OwnedJobObservation:
            return OwnedJobObservation(job_id, "UNKNOWN", alive, code)

        try:
            self._check_owner()
        except JobOwnerLost:
            return unknown("darwin_job_owner_lost")
        with self._lock:
            job = self._lookup_locked(job_id)
            if job is None:
                # Never adopted: records of other incarnations stay UNKNOWN.
                return unknown("darwin_job_not_owned")
            if job.reaped and not job.lost:
                return unknown("darwin_job_reaped", alive=False)
            if job.lost:
                return unknown(job.reason_code)
            if self._fault is not None:
                return unknown(self._fault)
            if self._verified_record_locked(job) is None:
                return unknown(job.reason_code)
            if job.exit_seen:
                return OwnedJobObservation(
                    job_id, "OWNED", False, "darwin_job_exit_pending"
                )
            return OwnedJobObservation(job_id, "OWNED", True, "darwin_job_owned")

    def signal_owned_group(
        self, job_id: str, intent: Literal["terminate", "kill"]
    ) -> None:
        self._check_owner()
        number = {"terminate": signal.SIGTERM, "kill": signal.SIGKILL}.get(intent)
        if number is None:
            raise ValueError("intent must be terminate or kill")
        with self._lock:
            job = self._lookup_locked(job_id)
            if job is None:
                raise UnverifiedJobProcess("darwin_job_not_owned")
            job.stop_requested = True
            self._signal_group_locked(job, number)

    def _signal_group_locked(self, job: _OwnedJob, number: int) -> None:
        if job.lost:
            raise UnverifiedJobProcess(job.reason_code)
        if job.reaped:
            raise UnverifiedJobProcess("darwin_job_already_reaped")
        record = self._verified_record_locked(job)
        if record is None:
            raise UnverifiedJobProcess(job.reason_code)
        # setsid at spawn: the group is the leader's pid. Never redirect a
        # signal to a group the leader moved to.
        if record.group != job.pid or record.group == os.getpgrp():
            self._mark_lost_locked(job, "darwin_job_group_unverified")
            raise UnverifiedJobProcess(job.reason_code)
        try:
            os.killpg(job.pid, number)
        except ProcessLookupError:
            # Only the unreaped zombie leader is left: nothing to deliver. It
            # may have exited after the read above (RJ1-F7): read it again.
            record = self._child_record(job.pid) or record
            if record.state != 5 or record.birth != job.birth:  # SZOMB
                raise JobSignalDeliveryError("darwin_job_signal_partial") from None
        except OSError as exc:
            partial = exc.errno == errno.EPERM
            raise JobSignalDeliveryError(
                "darwin_job_signal_partial" if partial else "darwin_job_signal_failed"
            ) from None

    def close(self) -> Sequence[OwnedJobExit]:
        """TERM, grace, KILL, reap (unreapable -> UNKNOWN); every unreleased exit."""
        self._check_owner()
        with self._lock:
            if self._closed:
                return ()
            self._closing = True
            targets = [
                job for job in self._jobs.values() if not job.reaped and not job.lost
            ]
            for job in targets:
                job.close_signalled = not job.exit_seen
        for number, grace_s in self._graces:
            with self._lock:
                for job in targets:
                    if not job.exit_seen and not job.reaped and not job.lost:
                        try:
                            self._signal_group_locked(job, number)
                        except (UnverifiedJobProcess, JobSignalDeliveryError):
                            pass
            self._await_reaped(targets, grace_s)
        with self._lock:
            for job in targets:
                if job.exit is None and not job.lost:
                    self._mark_lost_locked(job, "darwin_job_reap_timeout")
            self._closed = True
            self._changed.notify_all()
            exits = tuple(
                job.exit for job in self._jobs.values() if job.exit is not None
            )
        if self._reaper is not None:
            self._reaper.join(timeout=1.0)
        if sys.platform == "darwin":
            with self._lock:
                queue, self._queue = self._queue, None
            if queue is not None:
                queue.close()
        return exits

    def _await_reaped(self, targets: Sequence[_OwnedJob], grace_s: float) -> None:
        deadline = time.monotonic() + grace_s
        while True:
            with self._lock:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or all(job.reaped or job.lost for job in targets):
                    return
                if self.reaper_running:
                    self._changed.wait(min(remaining, _REAPER_POLL_S))
                    continue
            # No reaper thread: close() drives the same sole reap path.
            try:
                self.reap_exits(min(remaining, _REAPER_POLL_S))
            except Exception:  # noqa: BLE001 - unreaped targets -> reap_timeout
                self._record_fault()
                return
