"""Read-only witness observations and an ephemeral, sole-parent child fence.

No persisted PID, generation string or witness observation is signal authority.
The private foreground fence creates its own child; it cannot adopt a PID.
Its host must reserve SIGCHLD and child reaping for this owner. Competing native
waiters in the same process are outside this cooperative contract. Runtime
enablement requires separate exact-source review and composition acceptance.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from collections.abc import Mapping, Sequence
from threading import RLock
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

_FOREGROUND_SCOPE = "leader only; descendants_unverified=true"
_PROCESS_TOKEN = object()


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
    ) -> None:
        if not _is_darwin():
            raise _unavailable("native_capability_unavailable")
        if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
            raise _unknown("darwin_exclusive_reaper_required")
        self._lock = RLock()
        self._owner_pid = os.getpid()
        self._owner_token = _process_token()
        self._generation = uuid4().hex
        self._lost = False
        self._reaped = False
        self._status: int | None = None
        self._pid = os.posix_spawn(
            argv[0],
            list(argv),
            env,
            file_actions=file_actions,
            setpgroup=0,
            setsigmask=(),
            setsigdef=(signal.SIGPIPE, signal.SIGTERM, signal.SIGINT, signal.SIGCHLD),
        )

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

    def _poll_locked(self) -> int | None:
        if self._reaped:
            return self._status
        try:
            waited, status = os.waitpid(self._pid, os.WNOHANG)
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
        return self._status

    def poll(self, generation: str) -> int | None:
        self._check_owner(generation)
        with self._lock:
            self._check_locked(generation)
            return self._poll_locked()

    def _signal_locked(self, number: int) -> None:
        if self._reaped:
            raise _unknown("darwin_foreground_already_reaped", spawned=True)
        try:
            os.killpg(self._pid, number)
        except OSError:
            raise _unknown(
                "darwin_foreground_signal_unverified", spawned=True
            ) from None

    def cleanup(self, generation: str) -> None:
        """Bound TERM/KILL and reap; never certify descendant closure.

        Keep the leader unreaped throughout the TERM grace interval, even if it
        has exited. This reserves its identity until the last group signal.
        Holding this lock excludes concurrent poll/cancel/reap paths.
        """
        self._check_owner(generation)
        with self._lock:
            self._check_locked(generation)
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
            while self._poll_locked() is None:
                if time.monotonic() >= deadline:
                    self._lost = True
                    raise _unknown("darwin_foreground_reap_timeout", spawned=True)
                time.sleep(0.01)
            if failure is not None:
                raise failure
