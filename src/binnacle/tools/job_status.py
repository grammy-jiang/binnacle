"""job_status — check a background job, or list recent jobs.

Spec: docs/tools/run_command.md §4. Reads only disk (jobs.py), so it
works across `uvicorn --reload` and ChatGPT's per-call sessions.
"""

import logging
import time
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools.base import ToolResult
from pydantic import Field

from binnacle import jobs
from binnacle.callctx import current_call, current_call_started
from binnacle.config import get_settings

QUIET_AFTER_S = get_settings().jobs.quiet_after_s
LISTING_HISTORY_LIMIT = get_settings().jobs.listing_history_limit
LISTING_COMMAND_PREVIEW_CHARS = get_settings().jobs.listing_command_preview_chars
WAIT_MAX = get_settings().run_command.wait_max_s
log = logging.getLogger("binnacle.job_status")
_PERF_COUNTER = time.perf_counter

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "job_id": {"type": "string"},
        "state": {"type": "string"},
        "exit_code": {"type": ["integer", "null"]},
        "signal": {"type": ["integer", "null"]},
        "runtime_s": {"type": "number"},
        "last_output_age_s": {"type": ["number", "null"]},
        "quiet": {"type": "boolean"},
        "log_tail": {"type": "string"},
        "log_bytes": {"type": "integer"},
        "log_path": {"type": "string"},
        "command": {"type": "string"},
        "workdir": {"type": "string"},
        "waited_s": {"type": "number"},
        "processes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pid": {"type": "integer"},
                    "state": {"type": "string"},
                    "etime_s": {"type": "number"},
                    "cpu_s": {"type": "number"},
                    "cmd": {"type": "string"},
                },
            },
        },
        "jobs": {"type": "array", "items": {"type": "object"}},
    },
}


def _tail(text: str, n: int) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def _command_preview(command: str, keep_chars: int | None = None) -> str:
    """Compact one-line head+tail identity for a recent-jobs listing."""
    if keep_chars is None:
        keep_chars = LISTING_COMMAND_PREVIEW_CHARS
    display = command.replace("\n", "\\n")
    if len(display) <= keep_chars:
        return display
    head = keep_chars // 2
    tail = keep_chars - head
    omitted = len(display) - keep_chars
    return f"{display[:head]}…[{omitted} chars omitted]…{display[-tail:]}"


def _listing_rows(states: list[dict]) -> tuple[list[dict], int]:
    """All running jobs plus bounded recent non-running history, newest first."""
    rows: list[dict] = []
    history = 0
    running = 0
    for state in states:
        is_running = state["state"] == "running"
        if is_running:
            running += 1
        elif history < LISTING_HISTORY_LIMIT:
            history += 1
        else:
            continue
        rows.append(
            {
                "job_id": state["job_id"],
                "state": state["state"],
                "exit_code": state["exit_code"],
                "runtime_s": state["runtime_s"],
                "started_at": state["started_at"],
                "workdir": state["workdir"],
                "command": _command_preview(state["command"]),
            }
        )
    return rows, running


def _wait_for_exit(job_id: str, wait_seconds: int) -> tuple[dict | None, float]:
    """Block until the job is recorded exited, or the wait is up.

    Delegates to jobs.await_exit, which reads disk (the job may predate a
    uvicorn --reload) and bridges the brief post-death window before the
    reaper records the exit, so this never returns a false "unknown" for a
    job that is really finishing.
    """
    t0 = _PERF_COUNTER()
    state = jobs.await_exit(job_id, wait_seconds)
    return state, round(_PERF_COUNTER() - t0, 3)


def _elapsed_ms(start: float) -> float:
    return (_PERF_COUNTER() - start) * 1_000


def job_status_impl(
    job_id: str | None, tail_lines: int, wait_seconds: int = 0
) -> ToolResult:
    impl_start = _PERF_COUNTER()
    call_start = current_call_started.get()
    dispatch_ms = (impl_start - call_start) * 1_000 if call_start is not None else None
    if job_id is None:
        states = jobs.list_jobs()
        rows, running = _listing_rows(states)
        if not states:
            summary = "No jobs recorded."
        elif len(rows) == len(states):
            summary = f"{len(rows)} job(s), newest first."
        else:
            summary = (
                f"{len(rows)} of {len(states)} job(s) shown, newest first: "
                f"all {running} running plus up to {LISTING_HISTORY_LIMIT} recent "
                "non-running jobs."
            )
        log.info(
            "event=job_listing call=%s recorded_jobs=%s returned_jobs=%s "
            "running_jobs=%s history_limit=%s command_preview_chars=%s",
            current_call.get(),
            len(states),
            len(rows),
            running,
            LISTING_HISTORY_LIMIT,
            LISTING_COMMAND_PREVIEW_CHARS,
        )
        return ToolResult(content=summary, structured_content={"jobs": rows})

    wait_seconds = max(0, min(wait_seconds, WAIT_MAX))
    state_start = _PERF_COUNTER()
    if wait_seconds:
        state, waited = _wait_for_exit(job_id, wait_seconds)
    else:
        state, waited = jobs.job_state(job_id), 0.0
    state_ms = _elapsed_ms(state_start)
    if state is None:
        raise ToolError(
            f"No job with id {job_id!r}. Call job_status without a job_id to list recent jobs."
        )

    read_start = _PERF_COUNTER()
    log_text = jobs.read_log(job_id).decode("utf-8", errors="replace")
    read_log_ms = _elapsed_ms(read_start)
    quiet = (
        state["state"] == "running"
        and state["last_output_age_s"] is not None
        and state["last_output_age_s"] >= QUIET_AFTER_S
    )

    process_start = _PERF_COUNTER()
    processes = jobs.job_processes(state["pgid"]) if state["state"] == "running" else []
    process_scan_ms = _elapsed_ms(process_start)
    payload = {
        "job_id": job_id,
        "state": state["state"],
        "exit_code": state["exit_code"],
        "signal": state["signal"],
        "runtime_s": state["runtime_s"],
        "last_output_age_s": state["last_output_age_s"],
        "quiet": quiet,
        "log_tail": _tail(log_text, max(1, tail_lines)),
        "log_bytes": state["log_bytes"],
        "log_path": state["log_path"],
        "command": _command_preview(state["command"]),
        "workdir": state["workdir"],
        "processes": processes,
    }
    if wait_seconds:
        payload["waited_s"] = waited
    if state["state"] == "exited":
        rc = state["exit_code"]
        detail = (
            f"killed by signal {state['signal']}"
            if state["signal"] is not None
            else f"exited {rc}"
        )
        summary = f"Job {job_id} {detail} after {state['runtime_s']} s."
    elif quiet:
        summary = (
            f"Job {job_id} running but quiet for {state['last_output_age_s']} s "
            f"({state['runtime_s']} s total)."
        )
    else:
        summary = f"Job {job_id} running ({state['runtime_s']} s)."
    if wait_seconds and state["state"] == "running":
        summary += f" Still running after waiting {waited} s."
    impl_ms = _elapsed_ms(impl_start)
    dispatch_field = f"{dispatch_ms:.2f}" if dispatch_ms is not None else "na"
    log.info(
        "event=job_status_timing call=%s job_id=%s wait_requested_s=%s "
        "dispatch_ms=%s state_ms=%.2f read_log_ms=%.2f process_scan_ms=%.2f "
        "impl_ms=%.2f state=%s processes=%s log_bytes=%s",
        current_call.get(),
        job_id,
        wait_seconds,
        dispatch_field,
        state_ms,
        read_log_ms,
        process_scan_ms,
        impl_ms,
        state["state"],
        len(processes),
        state["log_bytes"],
    )
    return ToolResult(content=summary, structured_content=payload)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations={"readOnlyHint": True, "openWorldHint": False},
        output_schema=OUTPUT_SCHEMA,
    )
    def job_status(
        job_id: Annotated[
            str | None,
            Field(description="Job to check. Omit to list recent jobs."),
        ] = None,
        tail_lines: Annotated[
            int, Field(ge=1, description="Lines of merged output to tail.")
        ] = 100,
        wait_seconds: Annotated[
            int,
            Field(
                ge=0,
                le=WAIT_MAX,
                description="Block up to this long (max 50) for the job to exit before answering; 0 answers at once.",
            ),
        ] = 0,
    ) -> ToolResult:
        """Status of a job from run_command, or the recent-jobs list when
        job_id is omitted. Only needed when run_command returned a job_id.
        Call once with wait_seconds=50 to block until the job exits instead
        of polling; a job still running then is not killed. Returns state,
        exit code, output tail, and live processes; quiet=true means no
        recent output.
        """
        return job_status_impl(job_id, tail_lines, wait_seconds)
