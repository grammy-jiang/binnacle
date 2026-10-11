"""Read-only witness observations and an ephemeral, sole-parent child fence.

No persisted PID, generation string or witness observation is signal authority.
The private foreground fence creates its own child; it cannot adopt a PID.
Its host must reserve SIGCHLD and child reaping for this owner. Competing native
waiters in the same process are outside this cooperative contract. Runtime
enablement requires separate exact-source review and composition acceptance.
"""

from __future__ import annotations

import ctypes
import errno
import os
import resource
import select
import signal
import struct
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from threading import RLock
from typing import NamedTuple
from uuid import uuid4

from binnacle.platform.contracts.capability_contracts import (
    AuthorityUnknown,
    Capability,
    CapabilityState,
    CapabilityUnavailable,
    NativeCapabilityError,
)
from binnacle.platform.contracts.darwin_contracts import (
    AuthorityObservation,
    OwnedWitness,
)

_FOREGROUND_SCOPE = (
    "isolated process group; new process groups/sessions (setsid, set -m) "
    "are not tracked or terminated; descendants_unverified=true"
)
_PROCESS_TOKEN = object()

# For B0's adapter to record_direct_child_exit(job_id, rusage). Observers receive
# only the sole wait4's direct-child accounting, never a job-wide measurement.
DirectChildExitObserver = Callable[[resource.struct_rusage], None]


def _after_fork() -> None:
    # An inherited fence must stay invalid even if a later descendant eventually
    # receives the original parent's recycled numeric PID. No locks in this hook.
    global _PROCESS_TOKEN
    _PROCESS_TOKEN = object()


os.register_at_fork(after_in_child=_after_fork)


def _process_token() -> object:
    return _PROCESS_TOKEN


def _is_darwin() -> bool:
    return sys.platform == "darwin"


def _unknown(code: str, *, spawned: bool = False) -> AuthorityUnknown:
    error = AuthorityUnknown(
        code,
        Capability(
            CapabilityState.UNKNOWN,
            code,
            _FOREGROUND_SCOPE if spawned else "history only",
        ),
    )
    if spawned:
        error.args = (f"{code}; descendants_unverified=true",)
    return error


def _unavailable(code: str, *, spawned: bool = False) -> CapabilityUnavailable:
    error = CapabilityUnavailable(
        code, Capability(CapabilityState.UNAVAILABLE, code, _FOREGROUND_SCOPE)
    )
    if spawned:
        error.args = (f"{code}; descendants_unverified=true",)
    return error


def _unknown_observation(code: str) -> AuthorityObservation:
    return AuthorityObservation(
        Capability(CapabilityState.UNKNOWN, code, "history only; no signal authority"),
        None,
        membership_closed=False,
        can_signal=False,
    )


def observe_authority(
    job_id: str, *, witness: OwnedWitness | None
) -> AuthorityObservation:
    """Require a live witness; never infer absence or adopt numeric metadata."""
    if witness is None:
        return _unknown_observation("darwin_owner_witness_lost")
    try:
        observation = witness.observe(job_id)
    except (OSError, NativeCapabilityError, ValueError):
        return _unknown_observation("darwin_witness_unverified")
    generation = observation.generation
    if (
        generation is None
        or generation.job_id != job_id
        or not generation.manager_epoch
        or not generation.witness_epoch
        or observation.capability.state
        not in (CapabilityState.AVAILABLE, CapabilityState.LIMITED)
    ):
        return _unknown_observation("darwin_witness_unverified")
    return AuthorityObservation(
        Capability(
            CapabilityState.LIMITED,
            "darwin_witness_observed",
            "live enrollment observation only",
        ),
        generation,
        membership_closed=False,
        can_signal=False,
    )


class _ProcessRecord(NamedTuple):
    pid: int
    parent: int
    group: int
    state: int
    birth: tuple[int, int]


def _process_records(kind: int, identifier: int) -> list[_ProcessRecord]:
    """Public sysctl(3) KERN_PROC_PID/PGRP, LP64 Darwin kinfo_proc ABI.

    SDK sys/sysctl.h and sys/proc.h: size 648, p_starttime 0, p_stat 36,
    p_pid 40, e_ppid 560, e_pgid 564. Never libproc/private symbols.
    Validate size/fields and a self round-trip before spawning; fail closed.
    These observations can revoke the child fence, never create authority.
    """
    if (
        not _is_darwin()
        or ctypes.sizeof(ctypes.c_void_p) != 8
        or sys.byteorder != "little"
    ):
        raise OSError("unsupported kinfo_proc ABI")
    library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    query = library.sysctl
    query.argtypes = [
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    query.restype = ctypes.c_int
    mib = (ctypes.c_int * 4)(1, 14, kind, identifier)
    size = ctypes.c_size_t()
    if query(mib, 4, None, ctypes.byref(size), None, 0) != 0:
        raise OSError(ctypes.get_errno(), "sysctl size failed")
    if size.value > 648 * 65536:
        raise OSError("invalid kinfo_proc size")
    buffer = ctypes.create_string_buffer(size.value + 648 * 4)
    size.value = len(buffer)
    if query(mib, 4, buffer, ctypes.byref(size), None, 0) != 0:
        raise OSError(ctypes.get_errno(), "sysctl read failed")
    if size.value > len(buffer):
        raise OSError("invalid kinfo_proc size")
    return _decode_process_records(buffer.raw[: size.value])


def _decode_process_records(data: bytes) -> list[_ProcessRecord]:
    if len(data) % 648:
        raise OSError("invalid kinfo_proc layout")
    records = []
    for offset in range(0, len(data), 648):
        raw = data[offset : offset + 648]
        birth = struct.unpack_from("=qi", raw)
        record = _ProcessRecord(
            struct.unpack_from("=i", raw, 40)[0],
            struct.unpack_from("=i", raw, 560)[0],
            struct.unpack_from("=i", raw, 564)[0],
            raw[36],
            birth,
        )
        if (
            record.pid <= 0
            or record.parent < 0
            or record.group <= 0
            or record.state not in range(1, 6)
            or birth[0] <= 0
            or not 0 <= birth[1] < 1_000_000
        ):
            raise OSError("invalid kinfo_proc fields")
        records.append(record)
    return records


def _validate_process_layout() -> None:
    records = _process_records(1, os.getpid())
    if len(records) != 1 or (records[0].pid, records[0].parent, records[0].group) != (
        os.getpid(),
        os.getppid(),
        os.getpgrp(),
    ):
        raise OSError("kinfo_proc self round-trip failed")


class _ForegroundOwner:
    """Own one posix_spawn child and serialize *every* signal and reap.

    Construction spawns; no constructor or recovery path accepts a PID/PGID.
    The generation is an in-memory consistency fence, not a transferable right.
    No destructor or background waiter signals or reaps this child.
    """

    def __init__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        file_actions: Sequence[tuple],
        on_direct_child_exit: DirectChildExitObserver | None = None,
    ) -> None:
        if not _is_darwin():
            raise _unavailable("native_capability_unavailable")
        if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
            raise _unknown("darwin_exclusive_reaper_required")
        _validate_process_layout()
        self._lock = RLock()
        self._owner_pid = os.getpid()
        self._owner_token = _process_token()
        self._generation = uuid4().hex
        self._lost = False
        self._reaped = False
        self._exit_seen = False
        self._status: int | None = None
        self._on_direct_child_exit = on_direct_child_exit
        if sys.platform == "darwin":
            self._exit_queue: select.kqueue | None = None
        self._pid = os.posix_spawn(
            argv[0],
            list(argv),
            env,
            file_actions=file_actions,
            # A new session prevents other jobs joining this group and prevents
            # this session leader joining the manager's or a sibling's group.
            setsid=True,
            setsigmask=(),
            setsigdef=(signal.SIGPIPE, signal.SIGTERM, signal.SIGINT, signal.SIGCHLD),
        )
        self._birth: tuple[int, int] | None = None
        self._birth = self._owned_record_locked().birth

    @property
    def generation(self) -> str:
        return self._generation

    def _check_owner(self, generation: str) -> None:
        # Check before acquiring a lock that a forked process may inherit locked.
        if (
            os.getpid() != self._owner_pid
            or self._owner_token is not _process_token()
            or generation != self._generation
        ):
            raise _unknown("darwin_foreground_owner_lost", spawned=True)

    def _check_locked(self, generation: str) -> None:
        self._check_owner(generation)
        if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
            self._lost = True
        if self._lost:
            raise _unknown("darwin_foreground_owner_lost", spawned=True)

    def _close_exit_watch_locked(self) -> None:
        if sys.platform == "darwin" and self._exit_queue is not None:
            self._exit_queue.close()
            self._exit_queue = None

    def _exit_observed_locked(self) -> bool:
        """Observe without wait4: the zombie must still reserve the group ID.

        Retain NOTE_EXIT registration across polls. If the child exits before
        registration, Darwin reports ESRCH: under the exclusive-reaper contract
        it is our unreaped zombie, not a reusable PID. Both paths clean the group
        before wait4. No waitid/WNOWAIT dependency on Python 3.10–3.12.
        """
        if self._exit_seen:
            return True
        if sys.platform == "darwin":
            changes = []
            if self._exit_queue is None:
                self._exit_queue = select.kqueue()
                changes.append(
                    select.kevent(
                        self._pid,
                        filter=select.KQ_FILTER_PROC,
                        flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                        fflags=select.KQ_NOTE_EXIT,
                    )
                )
            try:
                events = self._exit_queue.control(changes, 1, 0)
                if not events:
                    return False
                observed = events[0]
                if (
                    observed.ident == self._pid
                    and observed.filter == select.KQ_FILTER_PROC
                ):
                    if observed.flags & select.KQ_EV_ERROR:
                        if observed.data == errno.ESRCH and changes:
                            self._exit_seen = True
                            return True
                        raise OSError(observed.data, "kqueue registration failed")
                    if observed.fflags & select.KQ_NOTE_EXIT:
                        self._exit_seen = True
                        return True
                self._lost = True
                raise _unknown("darwin_foreground_exit_unverified", spawned=True)
            except ProcessLookupError:
                # The public API can also report a failed registration as an
                # exception rather than an EV_ERROR event.
                if changes:
                    self._exit_seen = True
                    return True
                self._lost = True
                raise _unknown("darwin_foreground_owner_lost", spawned=True) from None
            except BaseException:
                self._close_exit_watch_locked()
                raise
        raise _unavailable("native_capability_unavailable")

    def _reap_locked(self, generation: str) -> int | None:
        """Called only after the final group signal, never to observe exit."""
        self._check_locked(generation)
        if self._reaped:
            return self._status
        try:
            waited, status, usage = os.wait4(self._pid, os.WNOHANG)
        except OSError:
            self._lost = True
            raise _unknown("darwin_foreground_reap_unverified", spawned=True) from None
        if waited:
            # Invalidate before unlocking, including any unexpected wait result.
            self._reaped = True
            if waited != self._pid or not (
                os.WIFEXITED(status) or os.WIFSIGNALED(status)
            ):
                self._lost = True
                raise _unknown("darwin_foreground_reap_unverified", spawned=True)
            self._status = os.waitstatus_to_exitcode(status)
            self._check_locked(generation)
            observer, self._on_direct_child_exit = self._on_direct_child_exit, None
            if observer is not None:
                # Invalidate first: callback failure or reentry cannot cause a
                # second reap, another signal or duplicate accounting delivery.
                try:
                    observer(usage)
                except Exception:  # noqa: BLE001 - sanitize the injected observer boundary
                    raise _unknown(
                        "darwin_foreground_exit_observer_failed", spawned=True
                    ) from None
        return self._status

    def poll(self, generation: str) -> int | None:
        self._check_owner(generation)
        with self._lock:
            self._check_locked(generation)
            if not self._reaped and self._exit_observed_locked():
                self.cleanup(generation)
            return self._status

    def _owned_record_locked(self) -> _ProcessRecord:
        try:
            records = _process_records(1, self._pid)
            if len(records) == 1:
                record = records[0]
                if (
                    record.pid == self._pid
                    and record.parent == self._owner_pid
                    and (self._birth is None or record.birth == self._birth)
                ):
                    return record
        except OSError:
            pass
        self._lost = True
        raise _unknown("darwin_foreground_owner_lost", spawned=True)

    def _signal_locked(self, number: int) -> None:
        if self._reaped:
            raise _unknown("darwin_foreground_already_reaped", spawned=True)
        record = self._owned_record_locked()
        failure = False
        # setsid at spawn provides kernel membership isolation. Never redirect
        # a group signal if a leader unexpectedly moved; retain direct custody.
        if record.group != self._pid or record.group == os.getpgrp():
            failure = True
        else:
            try:
                os.killpg(self._pid, number)
            except ProcessLookupError:
                pass
            except OSError as exc:
                failure = True
                if exc.errno == errno.EPERM:
                    record = self._owned_record_locked()
                    try:
                        members = _process_records(2, self._pid)
                        failure = not (record.state == 5 and members == [record])
                    except OSError:
                        pass
        # Also supervise a moved leader, without ever signaling its new group.
        record = self._owned_record_locked()
        if record.state != 5:
            try:
                os.kill(self._pid, number)
            except OSError:
                failure = True
        if failure:
            raise _unknown("darwin_foreground_signal_unverified", spawned=True)

    def cleanup(self, generation: str) -> None:
        """TERM, 0.1 s grace, KILL, then reap on completion, timeout or cancel.

        Keep the leader unreaped throughout the TERM grace interval, even if it
        has exited. This reserves its identity until the last group signal.
        Holding this lock excludes concurrent poll/cancel/reap paths.
        Members remaining in the isolated group are terminated. Descendants
        leaving it via setpgid, setsid or shell job control are not tracked.
        A public snapshot before each signal detects a completed foreign reap;
        an uncooperative waiter racing the syscall still violates sole ownership.
        Never certify descendant closure.
        """
        self._check_owner(generation)
        with self._lock:
            self._check_locked(generation)
            self._close_exit_watch_locked()
            if self._reaped:
                return
            failure: AuthorityUnknown | None = None
            for number in (signal.SIGTERM, signal.SIGKILL):
                self._check_locked(generation)
                try:
                    self._signal_locked(number)
                except AuthorityUnknown as exc:
                    failure = exc
                if number == signal.SIGTERM:
                    time.sleep(0.1)
            deadline = time.monotonic() + 2.0
            while self._reap_locked(generation) is None:
                if time.monotonic() >= deadline:
                    self._lost = True
                    raise _unknown("darwin_foreground_reap_timeout", spawned=True)
                time.sleep(0.01)
            if failure is not None:
                raise failure
