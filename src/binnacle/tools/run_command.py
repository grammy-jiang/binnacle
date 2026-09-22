"""run_command — run a shell command, wait-not-kill (yields a job_id).

Spec: docs/tools/run_command.md. Shared job machinery: jobs.py.
"""

import hashlib
import logging
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools.base import ToolResult
from pydantic import Field

from binnacle import jobs
from binnacle.callctx import current_argument_names, current_call, current_client
from binnacle.config import get_settings
from binnacle.paths import resolve_path

RUN_SETTINGS = get_settings().run_command
RUN_WAIT_DEFAULT = RUN_SETTINGS.wait_default_s
RUN_WAIT_MAX = RUN_SETTINGS.wait_max_s
log = logging.getLogger("binnacle.run_command")

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "job_id": {"type": "string"},
        "state": {"type": "string", "enum": ["exited", "running"]},
        "exit_code": {"type": ["integer", "null"]},
        "signal": {"type": ["integer", "null"]},
        "output": {"type": "string"},
        "truncated": {"type": "boolean"},
        "output_bytes": {"type": "integer"},
        "duration_s": {"type": "number"},
        "runtime_s": {"type": "number"},
        "log_path": {"type": "string"},
        "workdir": {"type": "string"},
        "background_job": {"type": "boolean"},
    },
    "required": ["job_id", "state"],
}


def _tail(text: str, n: int) -> tuple[str, int]:
    """Last n lines of text and how many lines were dropped."""
    lines = text.splitlines(keepends=True)
    if len(lines) <= n:
        return text, 0
    return "".join(lines[-n:]), len(lines) - n


def run_command_impl(
    command: str,
    workdir: str,
    wait_seconds: int,
    background: bool,
    stdin: str | None,
    tail_lines: int | None = None,
) -> ToolResult:
    resolved = resolve_path(workdir)
    if not resolved.is_dir():
        raise ToolError(
            f"workdir is not a directory: {resolved}. "
            f"Use a directory inside ~/Projects or /tmp."
        )
    wait_seconds = max(1, min(wait_seconds, RUN_WAIT_MAX))
    client = current_client.get()
    auto_background = (
        not background
        and "background" not in current_argument_names.get()
        and RUN_SETTINGS.should_auto_background(client, command)
    )
    effective_background = background or auto_background
    if auto_background:
        log.info(
            "event=run_command_auto_background call=%s client=%s command_hash=%s",
            current_call.get(),
            client or "-",
            hashlib.sha256(command.encode()).hexdigest()[:12],
        )
    initial_wait = jobs.WARMUP_S if effective_background else float(wait_seconds)
    try:
        job_id = jobs.start_and_wait(command, resolved, stdin, initial_wait)
    except (OSError, RuntimeError) as e:
        raise ToolError(f"Could not start the job: {e}. Run `binnacle doctor`.") from e

    state = jobs.job_state(job_id)
    log_text = jobs.read_log(job_id).decode("utf-8", errors="replace")
    dropped = 0
    if tail_lines is not None:
        log_text, dropped = _tail(log_text, tail_lines)
    output, truncated = jobs.clip_head_tail(log_text)
    if dropped:
        output = (
            f"[… {dropped} earlier lines omitted (tail_lines={tail_lines}) …]\n"
            + output
        )
        truncated = True

    if state and state["state"] == "exited":
        payload = {
            "job_id": job_id,
            "state": "exited",
            "exit_code": state["exit_code"],
            "output": output,
            "truncated": truncated,
            "output_bytes": state["log_bytes"],
            "duration_s": state["runtime_s"],
            "log_path": state["log_path"],
            "workdir": str(resolved),
            "background_job": False,
        }
        if state["signal"] is not None:
            payload["signal"] = state["signal"]
        rc = state["exit_code"]
        if state["signal"] is not None:
            summary = f"Command killed by signal {state['signal']} after {state['runtime_s']} s."
        elif rc == 0:
            summary = f"Command exited 0 in {state['runtime_s']} s."
        else:
            summary = f"Command exited {rc} in {state['runtime_s']} s."
        # The command finished inline; there is no lingering job. Say so, because
        # models otherwise poll job_status to check (measured: 50 such no-arg
        # calls in a week, docs/usage-analysis-2026-09-06.md).
        summary += " It finished synchronously; no background job was created, so no job_status or stop_job is needed."
        return ToolResult(content=summary, structured_content=payload)

    # still running → hand back the job_id
    payload = {
        "job_id": job_id,
        "state": "running",
        "output": output,
        "truncated": truncated,
        "output_bytes": state["log_bytes"] if state else 0,
        "runtime_s": state["runtime_s"] if state else 0,
        "log_path": state["log_path"] if state else "",
        "workdir": str(resolved),
        "background_job": True,
    }
    reason = (
        "started in background by local policy"
        if auto_background
        else "started in background"
        if background
        else f"still running after {wait_seconds} s"
    )
    summary = (
        f"Command {reason}; job_id={job_id}. Continue independent work; "
        "call job_status once when the result is needed, or stop_job to cancel."
    )
    return ToolResult(content=summary, structured_content=payload)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "openWorldHint": True,
        },
        output_schema=OUTPUT_SCHEMA,
    )
    def run_command(
        command: Annotated[str, Field(description="Shell command, run as bash -c.")],
        workdir: Annotated[
            str,
            Field(
                description="Working directory; absolute (~ ok) or relative to ~/Projects. Must be inside ~/Projects or /tmp."
            ),
        ] = "~/Projects",
        wait_seconds: Annotated[
            int,
            Field(
                ge=1,
                le=RUN_WAIT_MAX,
                description="Seconds to wait before yielding a job_id (max 50).",
            ),
        ] = RUN_WAIT_DEFAULT,
        background: Annotated[
            bool,
            Field(
                description="Return at once with a job_id after a 1 s warm-up. Local policy may also auto-background matching commands."
            ),
        ] = False,
        stdin: Annotated[
            str | None, Field(description="Text piped to the command's stdin.")
        ] = None,
        tail_lines: Annotated[
            int | None,
            Field(
                ge=1,
                description="Return only the last N lines of output (no need to pipe through tail).",
            ),
        ] = None,
    ) -> ToolResult:
        """Run a shell command with bash -c; several commands can go in one
        call (set -e; a && b). Waits up to wait_seconds; a command still
        running then is not killed: you get a job_id for job_status and
        stop_job. A command that finished created no job. Output merges
        stdout and stderr.
        """
        return run_command_impl(
            command, workdir, wait_seconds, background, stdin, tail_lines
        )
