"""Process mechanics independent of job policy, storage, and accounting."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal, Protocol


class UnverifiedJobProcess(RuntimeError):
    """The platform cannot prove signal ownership; no target may be signaled."""


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
