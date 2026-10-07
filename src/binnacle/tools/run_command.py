"""run_command — run a shell command, wait-not-kill (yields a job_id).

Spec: docs/tools/run_command.md. Shared job machinery: jobs.py.
"""

from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools.base import ToolResult
from pydantic import Field

from binnacle import command_execution
from binnacle.command_backend import create_command_backend
from binnacle.config import RootsSettings, RunCommandSettings, get_settings
from binnacle.errors import CodedToolError
from binnacle.features.commands.command_contracts import CommandBackend, CommandFailure
from binnacle.paths import resolve_path

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


def run_command_impl(
    command: str,
    workdir: str,
    wait_seconds: int,
    background: bool,
    stdin: str | None,
    tail_lines: int | None = None,
    *,
    roots: RootsSettings | None = None,
    settings: RunCommandSettings | None = None,
    backend: CommandBackend | None = None,
) -> ToolResult:
    settings = get_settings().run_command if settings is None else settings
    resolved = resolve_path(workdir, roots=roots)
    if not resolved.is_dir():
        raise CodedToolError(
            "workdir_not_directory",
            f"workdir is not a directory: {resolved}. "
            f"Use a directory inside ~/Projects or /tmp.",
        )
    backend = create_command_backend() if backend is None else backend
    try:
        reply = command_execution.run_command(
            command,
            resolved,
            wait_seconds,
            background,
            stdin,
            tail_lines,
            backend=backend,
            settings=settings,
        )
    except CommandFailure as exc:
        raise ToolError(str(exc)) from exc.__cause__
    return ToolResult(content=reply.summary, structured_content=reply.payload)


def register(
    mcp: FastMCP,
    *,
    roots: RootsSettings | None = None,
    settings: RunCommandSettings | None = None,
    backend: CommandBackend | None = None,
) -> None:
    if roots is None or settings is None:
        defaults = get_settings()
        roots = defaults.roots if roots is None else roots
        settings = defaults.run_command if settings is None else settings
    roots, settings = roots.model_copy(deep=True), settings.model_copy(deep=True)

    backend = create_command_backend() if backend is None else backend

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
                le=settings.wait_max_s,
                description="Seconds to wait for the command to finish before yielding a job_id (max 50); returns as soon as it finishes, so a long wait costs nothing.",
            ),
        ] = settings.wait_default_s,
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
        call (set -e; a && b). Waits up to wait_seconds and returns as soon
        as the command finishes; a command still running is not killed: you
        get a durable job_id for job_status and stop_job. Unless the user
        asked you to wait for completion, report its job_id/progress and
        return control; they can ask for status later. Suggest a check-back
        interval only when grounded. A finished command created no job.
        Output merges stdout and stderr.
        """
        return run_command_impl(
            command,
            workdir,
            wait_seconds,
            background,
            stdin,
            tail_lines,
            roots=roots,
            settings=settings,
            backend=backend,
        )
