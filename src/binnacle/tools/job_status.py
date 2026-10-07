"""job_status checks a job or lists recent jobs; docs/tools/run_command.md §4.
Disk state survives `uvicorn --reload` and ChatGPT's per-call sessions.
"""

from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools.base import ToolResult
from pydantic import Field

from binnacle import command_status
from binnacle.command_backend import create_command_backend
from binnacle.config import get_settings
from binnacle.features.commands.command_contracts import CommandBackend, CommandFailure

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
        "log_delta": {"type": "string"},
        "delta_start": {"type": "integer"},
        "delta_end": {"type": "integer"},
        "next_cursor": {"type": "string"},
        "has_more": {"type": "boolean"},
        "log_bytes": {"type": "integer"},
        "log_path": {"type": "string"},
        "command": {"type": "string"},
        "workdir": {"type": "string"},
        "waited_s": {"type": "number"},
        "wait_requested_s": {"type": "integer"},
        "wait_effective_s": {"type": "integer"},
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


def job_status_impl(
    job_id: str | None,
    tail_lines: int,
    wait_seconds: int = 0,
    *,
    backend: CommandBackend | None = None,
    cursor: str | None = None,
    quiet_after_s: int | None = None,
    history_limit: int | None = None,
    preview_chars: int | None = None,
    wait_max: int | None = None,
) -> ToolResult:
    impl_start = command_status.perf_counter()
    if quiet_after_s is None:
        quiet_after_s = get_settings().jobs.quiet_after_s
    if history_limit is None:
        history_limit = get_settings().jobs.listing_history_limit
    if preview_chars is None:
        preview_chars = get_settings().jobs.listing_command_preview_chars
    if wait_max is None:
        wait_max = get_settings().run_command.wait_max_s
    backend = create_command_backend() if backend is None else backend
    try:
        reply = command_status.job_status(
            job_id,
            tail_lines,
            wait_seconds,
            cursor=cursor,
            backend=backend,
            quiet_after_s=quiet_after_s,
            history_limit=history_limit,
            preview_chars=preview_chars,
            wait_max=wait_max,
            impl_start=impl_start,
        )
    except CommandFailure as exc:
        raise ToolError(str(exc)) from exc.__cause__
    return ToolResult(content=reply.summary, structured_content=reply.payload)


def register(
    mcp: FastMCP,
    *,
    backend: CommandBackend | None = None,
    quiet_after_s: int,
    history_limit: int,
    preview_chars: int,
    wait_max: int,
) -> None:
    backend = create_command_backend() if backend is None else backend

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
                le=wait_max,
                description="Block up to this long (max 50) for the job to exit; returns as soon as it exits, so a long wait costs nothing. 0 answers at once.",
            ),
        ] = 0,
        cursor: Annotated[
            str | None,
            Field(
                description='"start" reads from the beginning, "end" from now; otherwise the next_cursor from your last cursor call for this job.'
            ),
        ] = None,
    ) -> ToolResult:
        """Status of a job from run_command, or the recent-jobs list when
        job_id is omitted. Only needed when run_command returned a job_id.
        A positive wait blocks up to the requested duration (max 50 seconds)
        and returns as soon as the job exits; waiting never kills a
        still-running job. For complete output across turns, pass cursor
        ("start", or the next_cursor you got) and drain until has_more is
        false. Once caught up and still running, return control unless the
        user asked to wait; a later turn or new chat can resume by
        job_id/cursor. Keep cursor internal unless asked. Returns lifecycle
        fields, output, and live processes; quiet=true means no recent output.
        """
        return job_status_impl(
            job_id,
            tail_lines,
            wait_seconds,
            cursor=cursor,
            backend=backend,
            quiet_after_s=quiet_after_s,
            history_limit=history_limit,
            preview_chars=preview_chars,
            wait_max=wait_max,
        )
