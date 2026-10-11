"""Fail-closed native Commands pending exact-source R1/CR1 acceptance."""

from pathlib import Path
from typing import NoReturn

from binnacle.features.commands.command_contracts import CommandFailure
from binnacle.platform.contracts.darwin_contracts import ForegroundExecution


def refuse_commands() -> NoReturn:
    raise CommandFailure(
        "native_capability_unavailable: Darwin Commands are UNAVAILABLE; "
        "foreground execution requires R1/CR1 approval; stop_job remains "
        "unavailable. FULL_PARITY_NO_GO."
    )


class RestrictedCommandBackend:
    """Never load Linux durable state or manufacture empty successful history."""

    def __init__(
        self, *, foreground_execution: ForegroundExecution | None = None
    ) -> None:
        self.foreground_execution = foreground_execution

    def require_available(self) -> None:
        refuse_commands()

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
