"""Transport-independent replies and the durable operations Commands consume."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class CommandReply:
    summary: str
    payload: dict


class CommandFailure(Exception):
    """An expected command failure with the existing human-readable message."""


class CommandBackend(Protocol):
    """Existing durable operations; records keep their legacy dictionary shapes."""

    def start_and_wait(
        self, command: str, workdir: Path, stdin: str | None, wait_seconds: float
    ) -> str: ...

    def stop_job(self, job_id: str) -> dict | None: ...

    def job_state(self, job_id: str) -> dict | None: ...

    def list_jobs(self) -> list[dict]: ...

    def await_exit(self, job_id: str, timeout: float) -> dict | None: ...

    def read_log(self, job_id: str) -> bytes: ...

    def read_log_range(
        self, job_id: str, start: int, max_bytes: int
    ) -> tuple[bytes, int]: ...

    def job_processes(self, job_id: str, max_cmd_chars: int = 200) -> list[dict]: ...

    @property
    def owner_mode(self) -> str: ...

    @property
    def warmup_s(self) -> float: ...

    @property
    def max_output_chars(self) -> int: ...
