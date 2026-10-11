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


def snapshot_size(state: dict | None) -> int | None:
    """The log size a job state measured, passed explicitly to its log read.

    r6 W2 X1e (SD-74): a reply's text and byte count describe one append-only
    snapshot. The size travels from the state call to the read call as a
    value; no backend keeps it per thread or per instance.
    """
    size = state.get("log_bytes") if isinstance(state, dict) else None
    return size if isinstance(size, int) else None


def read_log_snapshot(backend: CommandBackend, job_id: str, size: int | None) -> bytes:
    """The log prefix ``size`` measured; the whole log when no size was measured."""
    data = backend.read_log(job_id)
    return data if size is None else data[:size]


def read_log_range_snapshot(
    backend: CommandBackend, job_id: str, start: int, max_bytes: int, size: int | None
) -> tuple[bytes, int]:
    """A range read clamped to ``size`` while the log is still append-only."""
    data, size_at_open = backend.read_log_range(job_id, start, max_bytes)
    if size is None or not start <= size <= size_at_open:
        return data, size_at_open  # unmeasured, or truncated: never invent a prefix
    return data[: size - start], size


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
        "native_capability_unavailable: Commands are unavailable on macOS."
    )


STOP_JOB_UNAVAILABLE = (
    "stop_job is unavailable on macOS. "
    "run_command is available in foreground mode only (no background jobs)."
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
        raise CommandFailure(STOP_JOB_UNAVAILABLE)

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
