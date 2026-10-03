"""Process mechanics independent of job policy, storage, and accounting."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import BinaryIO, Literal, Protocol


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

    def boot_id(self) -> str: ...
