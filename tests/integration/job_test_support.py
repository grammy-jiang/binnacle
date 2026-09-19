"""Shared call helpers for job integration tests."""

from binnacle.tools import job_status as js
from binnacle.tools import run_command as rc
from binnacle.tools import stop_job as sj


def run(
    command: str,
    workdir: str = "/tmp",
    wait_seconds: int = 10,
    background: bool = False,
    stdin: str | None = None,
    tail_lines: int | None = None,
) -> dict:
    payload = rc.run_command_impl(
        command, workdir, wait_seconds, background, stdin, tail_lines
    ).structured_content
    assert payload is not None
    return payload


def status(job_id=None, tail_lines: int = 100, wait_seconds: int = 0) -> dict:
    payload = js.job_status_impl(job_id, tail_lines, wait_seconds).structured_content
    assert payload is not None
    return payload


def stop(job_id: str) -> dict:
    payload = sj.stop_job_impl(job_id).structured_content
    assert payload is not None
    return payload
