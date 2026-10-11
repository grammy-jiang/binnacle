"""Darwin process adapter: disabled runtime, reviewable foreground mechanism.

FULL_PARITY_NO_GO. The public foreground entrypoint intentionally cannot be
enabled by configuration, environment, witness state or request fields. R1 and
CR1 approval of the exact candidate plus B0 wiring are still required. Native
tests exercise the private runner directly; this is not runtime acceptance.
Durable launch/stop and historical PID adoption remain unavailable.
"""

from __future__ import annotations

import fcntl
import math
import os
import selectors
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import BinaryIO, Literal
from uuid import uuid4

from binnacle.platform.contracts.darwin_contracts import (
    AuthorityObservation,
    ForegroundRequest,
    ForegroundResult,
    OwnedWitness,
)
from binnacle.platform.contracts.process_contracts import (
    JobProcessIdentity,
    JobSignalLease,
    ProcessHandle,
    UnverifiedJobProcess,
)
from binnacle.platform.darwin.process_authority import (
    _ForegroundOwner,
    _is_darwin,
    _unavailable,
    _unknown,
    observe_authority,
)


class DarwinProcessBackend:
    def __init__(self, *, witness: OwnedWitness | None = None) -> None:
        self._witness = witness

    def authority(self, job_id: str) -> AuthorityObservation:
        return observe_authority(job_id, witness=self._witness)

    def run_foreground(
        self, request: ForegroundRequest, *, cancel: Event
    ) -> ForegroundResult:
        raise _unavailable("native_capability_unavailable")

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
    """Private native qualification harness; no public runtime enable switch.

    Capture settings once at composition, never widen the captured limit from a
    request. B0 must supply the accepted settings and exclusive-reaper host when
    a future reviewed change opens the public gate.
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
        self, request: ForegroundRequest, *, cancel: Event
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
            owner = _ForegroundOwner(argv, env=env, file_actions=pipes.actions())
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
