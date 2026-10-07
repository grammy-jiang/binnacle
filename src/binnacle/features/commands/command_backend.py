"""Stateless bridge to the existing process-owned durable job engine."""

from importlib import import_module
from pathlib import Path

from binnacle.features.commands.command_contracts import CommandBackend


class DurableCommandBackend:
    """Delegate without owning configuration, processes, caches, or resources."""

    __slots__ = ()

    def start_and_wait(
        self, command: str, workdir: Path, stdin: str | None, wait_seconds: float
    ) -> str:
        from binnacle import job_owner

        return job_owner.start_and_wait(command, workdir, stdin, wait_seconds)

    def stop_job(self, job_id: str) -> dict | None:
        from binnacle import job_owner

        return job_owner.stop_job(job_id)

    def job_state(self, job_id: str) -> dict | None:
        from binnacle import jobs

        return jobs.job_state(job_id)

    def list_jobs(self) -> list[dict]:
        from binnacle import jobs

        return jobs.list_jobs()

    def await_exit(self, job_id: str, timeout: float) -> dict | None:
        from binnacle import jobs

        return jobs.await_exit(job_id, timeout)

    def read_log(self, job_id: str) -> bytes:
        from binnacle import jobs

        return jobs.read_log(job_id)

    def read_log_range(
        self, job_id: str, start: int, max_bytes: int
    ) -> tuple[bytes, int]:
        from binnacle import jobs

        return jobs.read_log_range(job_id, start, max_bytes)

    def job_processes(self, pgid: int, max_cmd_chars: int = 200) -> list[dict]:
        from binnacle import jobs

        return jobs.job_processes(pgid, max_cmd_chars)

    @property
    def owner_mode(self) -> str:
        from binnacle import jobs

        return jobs.OWNER_MODE

    @property
    def warmup_s(self) -> float:
        from binnacle import jobs

        return jobs.WARMUP_S

    @property
    def max_output_chars(self) -> int:
        from binnacle import jobs

        return jobs.RUN_MAX_OUTPUT_CHARS


def create_command_backend() -> CommandBackend:
    """Capture engine settings at default selection, before accepting requests."""
    import_module("binnacle.jobs")
    import_module("binnacle.job_owner")
    return DurableCommandBackend()
