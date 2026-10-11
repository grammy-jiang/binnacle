"""Darwin process adapter: scope-injected, bounded foreground mechanism.

FULL_PARITY_NO_GO. Only composition can inject the foreground runner, following
the source-controlled release scope. Configuration, environment, witness state
and request fields cannot enable it. The committed scope remains unavailable;
test-supplied candidate scopes are not release acceptance.
Durable launch/stop and historical PID adoption remain unavailable.
On completion the private runner terminates background members of its owned
group before reaping the leader. Processes that leave the group (setpgid,
setsid, shell set -m) are not tracked; every result still reports descendants_unverified=true.
"""

from __future__ import annotations

import fcntl
import math
import os
import selectors
import subprocess  # TimeoutExpired only; no process is created or waited here
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Event, RLock
from typing import BinaryIO, Literal, Protocol
from uuid import uuid4

from binnacle.platform.contracts.darwin_contracts import (
    AuthorityObservation,
    ForegroundRequest,
    ForegroundResult,
    OwnedWitness,
)
from binnacle.platform.contracts.process_contracts import (
    JobOwnerLost,
    JobProcessIdentity,
    JobSignalLease,
    OwnedJobExit,
    ProcessHandle,
    UnverifiedJobProcess,
)
from binnacle.platform.darwin.process_authority import (
    DirectChildExitObserver,
    _ForegroundOwner,
    _is_darwin,
    _returncode,
    _unavailable,
    _unknown,
    observe_authority,
)


class DarwinProcessBackend:
    def __init__(
        self,
        *,
        witness: OwnedWitness | None = None,
        foreground_runner: _ForegroundRunner | None = None,
    ) -> None:
        self._witness = witness
        self._foreground_runner = foreground_runner

    @property
    def foreground_enabled(self) -> bool:
        return isinstance(self._foreground_runner, _ForegroundRunner)

    def validate_release_states(self, states: Mapping[str, str]) -> None:
        if states.get("stop_job", "UNAVAILABLE") != "UNAVAILABLE":
            raise RuntimeError("Darwin stop_job must remain UNAVAILABLE (gate: never)")
        enabled = any(
            states.get(tool, "UNAVAILABLE") != "UNAVAILABLE"
            for tool in ("run_command", "job_status")
        )
        if enabled and (
            states.get("run_command") != "LIMITED"
            or states.get("job_status", "UNAVAILABLE") not in ("LIMITED", "UNAVAILABLE")
            or not self.foreground_enabled
        ):
            raise RuntimeError(
                "Darwin Commands scope requires the A2 foreground runtime gate"
            )

    def authority(self, job_id: str) -> AuthorityObservation:
        return observe_authority(job_id, witness=self._witness)

    def run_foreground(
        self,
        request: ForegroundRequest,
        *,
        cancel: Event,
        on_direct_child_exit: DirectChildExitObserver | None = None,
    ) -> ForegroundResult:
        """Refuse without a scope-injected runner; retain the sole owner otherwise.

        Once enabled, the optional observer receives the sole wait4 rusage once
        under the owner lock/generation, including timeout/cancel cleanup. It
        must be bounded and must not wait on another thread using this owner.
        B0 may bind a job ID to A5's record_direct_child_exit; no second waiter
        or private runner access is needed. Callback failure is a typed error,
        never a retry or a job-wide resource measurement.
        """
        if self._foreground_runner is None:
            raise _unavailable("native_capability_unavailable")
        return self._foreground_runner.run_foreground(
            request, cancel=cancel, on_direct_child_exit=on_direct_child_exit
        )

    def launch(
        self,
        argv: Sequence[str],
        *,
        workdir: Path,
        env: Mapping[str, str],
        stdin: BinaryIO,
        output: BinaryIO,
    ) -> ProcessHandle:
        raise _unavailable("darwin_commands_unavailable")

    def starttime(self, pid: int) -> int | None:
        return None

    def alive(self, pid: int, starttime: int | None = None) -> bool:
        raise _unknown("darwin_process_identity_unknown")

    def processes(self, pgid: int, max_cmd_chars: int = 200) -> list[dict]:
        raise _unknown("darwin_process_membership_unknown")

    def descendants(self, pid: int) -> set[int]:
        raise _unknown("darwin_process_membership_unknown")

    def signal_job(
        self, pgid: int, strays: set[int], intent: Literal["terminate", "kill"]
    ) -> None:
        raise _unavailable("darwin_commands_unavailable")

    def identity_from_record(
        self, metadata: Mapping[str, object]
    ) -> JobProcessIdentity | None:
        # Even a live read-only witness is not foreground or durable signal proof.
        return None

    def open_job_signals(self, identity: JobProcessIdentity) -> JobSignalLease:
        raise UnverifiedJobProcess("darwin_commands_unavailable")

    def inspect_job(
        self, identity: JobProcessIdentity, max_cmd_chars: int = 200
    ) -> list[dict]:
        raise _unknown("darwin_process_membership_unknown")

    def boot_id(self) -> str:
        # No private sysctl/libproc substitute and no fabricated boot identity.
        raise _unknown("darwin_boot_identity_unavailable")


class _OwnedExitSource(Protocol):
    def wait(self, job_id: str, timeout: float | None) -> OwnedJobExit | None: ...

    def exit_for(self, job_id: str) -> OwnedJobExit | None: ...


class OwnedProcessHandle:
    """ProcessHandle over a manager-owned job (R4 J1).

    wait() blocks only on the owner's reaper condition. It never calls waitpid
    and never starts a waiter thread, and it keeps subprocess.TimeoutExpired.
    """

    def __init__(self, owner: _OwnedExitSource, job_id: str, pid: int) -> None:
        self._owner = owner
        self._job_id = job_id
        self._pid = pid

    @property
    def pid(self) -> int:
        return self._pid

    @property
    def returncode(self) -> int | None:
        return _returncode(self._owner.exit_for(self._job_id))

    def wait(self, timeout: float | None = None) -> int:
        # Decide from one exit snapshot: the reaper may reap between the
        # timed-out wait() and a later read, which is an exit, not a loss.
        result = self._owner.wait(self._job_id, timeout)
        if result is None:
            result = self._owner.exit_for(self._job_id)
            if result is None:
                raise subprocess.TimeoutExpired(
                    ["binnacle-job", self._job_id], timeout or 0.0
                )
        code = _returncode(result)
        if code is None:
            raise JobOwnerLost("darwin_job_reap_unverified")
        return code


@dataclass(slots=True)
class _OwnedJob:
    job_id: str
    pid: int
    birth: tuple[int, int]
    exit_seen: bool = False
    reaped: bool = False
    lost: bool = False
    reason_code: str = "darwin_job_owned"
    stop_requested: bool = False
    close_signalled: bool = False
    straggler_deadline: float | None = None
    exit: OwnedJobExit | None = None


class _OwnedExitTable:
    """Released jobs leave the scans; id and exit stay (no duplicate writer)."""

    _lock: RLock
    _jobs: dict[str, _OwnedJob]
    _by_pid: dict[int, _OwnedJob]
    _released: dict[str, _OwnedJob]

    def _check_owner(self) -> None:
        raise NotImplementedError

    def wait(self, job_id: str, timeout: float | None) -> OwnedJobExit | None:
        raise NotImplementedError

    def _lookup_locked(self, job_id: str) -> _OwnedJob | None:
        return self._jobs.get(job_id) or self._released.get(job_id)

    def handle(self, job_id: str) -> OwnedProcessHandle:
        """A ``ProcessHandle`` whose wait() is served by the reaper's condition."""
        with self._lock:
            job = self._lookup_locked(job_id)
            if job is None:
                raise UnverifiedJobProcess("darwin_job_not_owned")
            return OwnedProcessHandle(self, job_id, job.pid)

    def exit_for(self, job_id: str) -> OwnedJobExit | None:
        with self._lock:
            job = self._lookup_locked(job_id)
            return None if job is None else job.exit

    def release(self, job_id: str) -> None:
        """1.2.0-additive: ack a persisted terminal record; close() omits it."""
        self._check_owner()
        with self._lock:
            if job_id in self._released:
                return
            job = self._jobs.get(job_id)
            if job is None:
                raise UnverifiedJobProcess("darwin_job_not_owned")
            if job.exit is None and not job.lost:
                raise ValueError("darwin_job_not_terminal")
            del self._jobs[job_id]
            if self._by_pid.get(job.pid) is job:
                del self._by_pid[job.pid]
            self._released[job_id] = job


class _CommandPipes:
    """Own nonblocking duplex pipes; bounded work per pump prevents starvation."""

    def __init__(self, request: ForegroundRequest) -> None:
        self._fds: set[int] = set()
        self._input = (request.stdin or "").encode("utf-8")
        self._selector = selectors.DefaultSelector()
        self._offset = 0
        self.output = bytearray()
        self.output_bytes = 0
        self.truncated = False
        self._max_output = request.max_output_bytes
        self.eof = False
        self._spawned = False
        try:
            self.child_in, self.parent_in = self._pipe()
            self.parent_out, self.child_out = self._pipe()
            os.set_blocking(self.parent_in, False)
            os.set_blocking(self.parent_out, False)
            self._selector.register(self.parent_out, selectors.EVENT_READ)
            if self._input:
                self._selector.register(self.parent_in, selectors.EVENT_WRITE)
        except BaseException:
            self.close()
            raise

    def _pipe(self) -> tuple[int, int]:
        pair = os.pipe()
        self._fds.update(pair)
        result = []
        for fd in pair:
            if fd < 3:
                duplicate = fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 3)
                self._fds.add(duplicate)
                self._close_fd(fd)
                fd = duplicate
            result.append(fd)
        return result[0], result[1]

    def _close_fd(self, fd: int) -> None:
        if fd in self._fds:
            self._fds.remove(fd)
            os.close(fd)

    def actions(self) -> list[tuple]:
        return [
            (os.POSIX_SPAWN_DUP2, self.child_in, 0),
            (os.POSIX_SPAWN_DUP2, self.child_out, 1),
            (os.POSIX_SPAWN_DUP2, self.child_out, 2),
            *((os.POSIX_SPAWN_CLOSE, fd) for fd in sorted(self._fds)),
        ]

    def spawned(self) -> None:
        self._spawned = True
        self._close_fd(self.child_in)
        self._close_fd(self.child_out)
        if not self._input:
            self._close_fd(self.parent_in)

    def _read(self) -> None:
        try:
            chunk = os.read(self.parent_out, 65536)
        except BlockingIOError:
            return
        if not chunk:
            self.eof = True
            self._selector.unregister(self.parent_out)
            self._close_fd(self.parent_out)
            return
        self.output_bytes += len(chunk)
        self.output.extend(chunk[: max(0, self._max_output - len(self.output))])
        self.truncated |= self.output_bytes > self._max_output

    def _write(self) -> None:
        try:
            self._offset += os.write(
                self.parent_in, self._input[self._offset : self._offset + 65536]
            )
        except BlockingIOError:
            return
        except BrokenPipeError:
            self._offset = len(self._input)
        if self._offset == len(self._input):
            self._selector.unregister(self.parent_in)
            self._close_fd(self.parent_in)

    def pump(self, timeout_s: float) -> None:
        for key, _ in self._selector.select(timeout_s):
            if key.fd == self.parent_out:
                self._read()
            else:
                self._write()

    def drain(self) -> None:
        deadline = time.monotonic() + 0.2
        while not self.eof and time.monotonic() < deadline:
            self.pump(0.01)
        self.truncated |= not self.eof

    def close(self) -> None:
        self._selector.close()
        # Attempt every close; report failure instead of success with leaked FDs.
        failed = False
        for fd in tuple(self._fds):
            try:
                self._close_fd(fd)
            except OSError:
                failed = True
        if failed:
            raise _unknown(
                "darwin_foreground_pipe_close_unverified", spawned=self._spawned
            )


@dataclass(frozen=True)
class _ForegroundRunner:
    """Native mechanism injected only at the source-controlled scope boundary.

    Capture settings once at composition, never widen the captured limit from a
    request. The host must reserve exclusive child reaping for this owner.
    """

    foreground_limit_s: float
    wait_max_s: float

    def __post_init__(self) -> None:
        if not (
            math.isfinite(self.wait_max_s)
            and math.isfinite(self.foreground_limit_s)
            and 0 < self.foreground_limit_s <= self.wait_max_s <= 50
        ):
            raise _unavailable("darwin_foreground_limit_invalid")

    def _validate(self, request: ForegroundRequest, cancel: Event) -> None:
        if not _is_darwin():
            raise _unavailable("native_capability_unavailable")
        if (
            not math.isfinite(request.wait_seconds)
            or not math.isfinite(request.foreground_limit_s)
            or request.wait_seconds < 0
            or request.foreground_limit_s <= 0
            or request.max_output_bytes < 0
        ):
            raise _unavailable("darwin_foreground_request_invalid")
        if (
            request.background
            or request.foreground_limit_s > self.foreground_limit_s
            or request.wait_seconds > request.foreground_limit_s
            or request.wait_seconds == 0
        ):
            raise _unavailable("darwin_background_jobs_unavailable")
        if cancel.is_set():
            raise _unavailable("darwin_foreground_cancelled")

    def run_foreground(
        self,
        request: ForegroundRequest,
        *,
        cancel: Event,
        on_direct_child_exit: DirectChildExitObserver | None = None,
    ) -> ForegroundResult:
        self._validate(request, cancel)
        started = time.monotonic()
        try:
            pipes = _CommandPipes(request)
        except (OSError, ValueError):
            raise _unknown("darwin_foreground_io_failed") from None
        owner: _ForegroundOwner | None = None
        try:
            # Python's public posix_spawn has no cwd argument. Change directory
            # in the spawned bash only, passing both inputs as positional data.
            argv = [
                "/bin/bash",
                "--noprofile",
                "--norc",
                "-c",
                'cd -- "$1" && exec /bin/bash --noprofile --norc -c "$2"',
                "binnacle-foreground",
                str(request.workdir),
                request.command,
            ]
            env = {
                key: value
                for key, value in os.environ.items()
                if key not in ("BASH_ENV", "ENV")
            }
            owner = _ForegroundOwner(
                argv,
                env=env,
                file_actions=pipes.actions(),
                on_direct_child_exit=on_direct_child_exit,
            )
            pipes.spawned()
            status = self._wait(owner, pipes, request, cancel, started)
            pipes.drain()
            if cancel.is_set():
                raise _unavailable("darwin_foreground_cancelled", spawned=True)
            return ForegroundResult(
                execution_id=uuid4().hex,
                owner_generation=owner.generation,
                exit_code=status if status >= 0 else None,
                signal=-status if status < 0 else None,
                output=bytes(pipes.output),
                output_bytes=pipes.output_bytes,
                truncated=pipes.truncated,
                duration_s=time.monotonic() - started,
                descendants_unverified=True,
            )
        except BaseException as exc:
            if owner is not None:
                owner.cleanup(owner.generation)
            if isinstance(exc, (OSError, ValueError)):
                raise _unknown(
                    "darwin_foreground_io_failed", spawned=owner is not None
                ) from None
            raise
        finally:
            pipes.close()

    @staticmethod
    def _wait(
        owner: _ForegroundOwner,
        pipes: _CommandPipes,
        request: ForegroundRequest,
        cancel: Event,
        started: float,
    ) -> int:
        deadline = started + min(request.wait_seconds, request.foreground_limit_s)
        while True:
            if cancel.is_set():
                raise _unavailable("darwin_foreground_cancelled", spawned=True)
            if time.monotonic() >= deadline:
                raise _unavailable("darwin_background_jobs_unavailable", spawned=True)
            status = owner.poll(owner.generation)
            if status is not None:
                return status
            pipes.pump(min(0.01, max(0, deadline - time.monotonic())))
