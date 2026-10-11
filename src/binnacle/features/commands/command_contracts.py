"""Transport-independent replies and the durable operations Commands consume."""

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Literal, NoReturn, Protocol


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


def require_command_available(backend: CommandBackend) -> None:
    """Optional refusal gate before paths, telemetry or any operation is touched."""
    check = getattr(backend, "require_available", None)
    if check is not None:
        check()


@dataclass(frozen=True)
class ForegroundRequest:
    command: str
    workdir: Path
    stdin: str | None
    wait_seconds: float
    background: bool
    foreground_limit_s: float
    max_output_bytes: int


@dataclass(frozen=True)
class ForegroundResult:
    execution_id: str
    owner_generation: str
    exit_code: int | None
    signal: int | None
    output: bytes
    output_bytes: int
    truncated: bool
    duration_s: float
    descendants_unverified: Literal[True]


class ForegroundExecution(Protocol):
    def run_foreground(
        self, request: ForegroundRequest, *, cancel: Event
    ) -> ForegroundResult: ...


def refuse_commands() -> NoReturn:
    raise CommandFailure(
        "native_capability_unavailable: Darwin Commands are UNAVAILABLE; "
        "foreground execution requires R1/CR1 approval; stop_job remains "
        "unavailable. FULL_PARITY_NO_GO."
    )


class RestrictedCommandBackend:
    """Never load Linux durable state or manufacture empty successful history."""

    def __init__(
        self,
        *,
        foreground_execution: ForegroundExecution | None = None,
        release_states: dict[str, str] | None = None,
    ) -> None:
        self.foreground_execution = foreground_execution
        self.release_states = dict(release_states or {})

    def require_available(self) -> None:
        if self.release_states.get("run_command") != "LIMITED":
            refuse_commands()
        if self.foreground_execution is None:
            raise CommandFailure(
                "native_capability_unavailable: foreground provider missing"
            )

    owner_mode = "unavailable"
    warmup_s = 0.0
    max_output_chars = 0

    def start_and_wait(
        self, command: str, workdir: Path, stdin: str | None, wait_seconds: float
    ) -> str:
        refuse_commands()

    def stop_job(self, job_id: str) -> dict | None:
        refuse_commands()

    def job_state(self, job_id: str) -> dict | None:
        refuse_commands()

    def list_jobs(self) -> list[dict]:
        refuse_commands()

    def await_exit(self, job_id: str, timeout: float) -> dict | None:
        refuse_commands()

    def read_log(self, job_id: str) -> bytes:
        refuse_commands()

    def read_log_range(
        self, job_id: str, start: int, max_bytes: int
    ) -> tuple[bytes, int]:
        refuse_commands()

    def job_processes(self, job_id: str, max_cmd_chars: int = 200) -> list[dict]:
        refuse_commands()
