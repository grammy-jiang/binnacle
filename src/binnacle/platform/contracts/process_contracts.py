"""Process mechanics independent of job policy, storage, and accounting."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal, Protocol


class UnverifiedJobProcess(RuntimeError):
    """The platform cannot prove signal ownership; no target may be signaled."""


class JobSignalDeliveryError(RuntimeError):
    """One or more verified native process targets could not be signaled."""


@dataclass(frozen=True, slots=True)
class JobProcessIdentity:
    """An opaque native identity. Core must not inspect its host-specific value."""

    native: object


class JobSignalLease(Protocol):
    """Hold verified native signal targets through terminate and escalation."""

    def signal(self, intent: Literal["terminate", "kill"]) -> None: ...

    def close(self) -> None: ...


class ProcessHandle(Protocol):
    """A native process handle; wait preserves subprocess.TimeoutExpired."""

    @property
    def pid(self) -> int: ...

    @property
    def returncode(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...


class ProcessBackend(Protocol):
    """Launch and inspect processes without owning the durable job lifecycle."""

    def launch(
        self,
        argv: Sequence[str],
        *,
        workdir: Path,
        env: Mapping[str, str],
        stdin: BinaryIO,
        output: BinaryIO,
    ) -> ProcessHandle:
        """Launch formed argv using caller-owned binary files and environment."""
        ...

    def starttime(self, pid: int) -> int | None:
        """Return an opaque token compatible with persisted starttime values."""
        ...

    def alive(self, pid: int, starttime: int | None = None) -> bool: ...

    def processes(self, pgid: int, max_cmd_chars: int = 200) -> list[dict]: ...

    def descendants(self, pid: int) -> set[int]: ...

    def signal_job(
        self, pgid: int, strays: set[int], intent: Literal["terminate", "kill"]
    ) -> None:
        """Signal group then strays; leave group disappearance visible to jobs."""
        ...

    def identity_from_record(
        self, metadata: Mapping[str, object]
    ) -> JobProcessIdentity | None: ...

    def open_job_signals(self, identity: JobProcessIdentity) -> JobSignalLease:
        """Pin and validate owned native signal targets before any signal."""
        ...

    def inspect_job(
        self, identity: JobProcessIdentity, max_cmd_chars: int = 200
    ) -> list[dict]:
        """Use a verified native identity, never a core-level PGID."""
        ...

    def boot_id(self) -> str: ...


# Interface 1.2.0 (R4 J0): the frozen Darwin durable-job owner. Declarations only;
# no implementation exists at this revision and nothing here grants authority.

JobOwnerKind = Literal["manager", "embedded"]
"""The owner actually composed; release rows are chosen from it, never from config."""

OwnedJobAuthority = Literal["OWNED", "UNKNOWN"]
"""OWNED only for (pid, birth) spawned by this owner incarnation and not reaped."""

JOB_MANAGER_UNAVAILABLE = "job manager unavailable"
"""Prefix of the Linux per-call error; an unreachable manager is never a fallback."""

OWNER_LOST_STOP_REFUSED = "job stop is unavailable for jobs whose owner was lost"


class JobManagerUnavailable(RuntimeError):
    """The composed manager did not answer; controlled per-call, never a fallback."""


class JobOwnerLost(RuntimeError):
    """The job's owner incarnation is gone; its authority is UNKNOWN (D-1)."""


@dataclass(frozen=True, slots=True)
class OwnedJobProcess:
    """A leader spawned by this owner: setsid, so pgid == pid while it lives."""

    job_id: str
    pid: int
    pgid: int
    birth: int
    owner_instance_id: str
    boot_id: str


@dataclass(frozen=True, slots=True)
class OwnedJobExit:
    """Sole-reaper evidence; termination_reason uses the Linux vocabulary only."""

    job_id: str
    exit_code: int | None
    signal: int | None
    termination_reason: Literal[
        "normal_exit", "signal", "stop_requested", "owner_restart"
    ]


@dataclass(frozen=True, slots=True)
class OwnedJobObservation:
    """Uncertainty is UNKNOWN: alive is None and processes empty, never exited."""

    job_id: str
    authority: OwnedJobAuthority
    alive: bool | None
    reason_code: str


class DarwinJobOwner(Protocol):
    """Sole owner of durable Darwin jobs, resident only in the stable manager.

    One instance per manager process incarnation. It spawns leaders with
    posix_spawn(setsid=True) and a default signal disposition, registers
    kqueue EVFILT_PROC/NOTE_EXIT before spawn returns (ESRCH means the exit is
    already pending), and is the only caller of waitpid for its pids while
    SIGCHLD stays SIG_DFL. Signal authority exists only in the in-memory
    (pid, birth) table of this incarnation: a pid, pgid, birth or boot_id read
    from disk, a socket peer or the process table is never adopted. Jobs owned
    by any other incarnation report authority UNKNOWN and are never signalled.
    """

    @property
    def owner_instance_id(self) -> str: ...

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
        """Spawn a session leader after meta is reserved; exit watch armed first."""
        ...

    def wait(self, job_id: str, timeout: float | None) -> OwnedJobExit | None:
        """Wait on the reaper's condition; None means still running at timeout."""
        ...

    def reap_exits(self, timeout: float | None) -> Sequence[OwnedJobExit]:
        """kqueue NOTE_EXIT loop body: the sole waitpid(WNOHANG) caller."""
        ...

    def signal_owned_group(
        self, job_id: str, intent: Literal["terminate", "kill"]
    ) -> None:
        """killpg the owned pgid only while membership is proven.

        Raises UnverifiedJobProcess when the leader is unknown to this
        incarnation or when, after the leader was reaped, group membership
        cannot be proven; JobSignalDeliveryError on partial delivery.
        """
        ...

    def authority(self, job_id: str) -> OwnedJobObservation:
        """OWNED for a live owned leader; UNKNOWN for anything else unproven."""
        ...

    def close(self) -> Sequence[OwnedJobExit]:
        """Normal owner stop (R4-REQ-J1J2-no-orphans).

        Every owned group still led by an unreaped leader receives terminate,
        the Linux stop grace, then kill; leaders are reaped by the sole reaper
        and returned with termination_reason "owner_restart" so the manager
        persists a terminal record before it exits. A group that cannot be
        reaped is left UNKNOWN, never reported exited. Busy-stop refusal is
        a provisioner gate and does not weaken this contract.

        1.2.0 clarification: close(): leaders still running when close()
        begins get termination_reason=owner_restart; exits observed earlier
        keep their Linux reason; close() returns every exit not yet released.
        """
        ...
