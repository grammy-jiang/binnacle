"""run_command — run a shell command, wait-not-kill (yields a job_id).

Spec: docs/tools/run_command.md. Shared job machinery: jobs.py.
"""

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools.base import ToolResult
from pydantic import Field

from binnacle.config import RootsSettings, RunCommandSettings, get_settings
from binnacle.errors import CodedToolError
from binnacle.features.commands import command_execution
from binnacle.features.commands.command_backend import (
    DarwinManagerCommandBackend,
    create_command_backend,
    darwin_manager_description,
)
from binnacle.features.commands.command_contracts import (
    CommandBackend,
    CommandFailure,
    ForegroundRequest,
    RestrictedCommandBackend,
    require_command_available,
)
from binnacle.features.files.paths import resolve_path

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
    backend = create_command_backend() if backend is None else backend
    try:
        require_command_available(backend)
    except CommandFailure as exc:
        raise ToolError(str(exc)) from exc
    settings = get_settings().run_command if settings is None else settings
    resolved = resolve_path(workdir, roots=roots)
    if not resolved.is_dir():
        raise CodedToolError(
            "workdir_not_directory",
            f"workdir is not a directory: {resolved}. "
            f"Use a directory inside ~/Projects or /tmp.",
        )
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
    restricted = isinstance(backend, RestrictedCommandBackend)
    # The embedded macOS owner refuses background and kills at the limit, so
    # its parameters must not advertise jobs it never creates.
    wait_help = (
        f"Seconds to wait for the command to finish (max {settings.wait_max_s}); "
        "on macOS foreground mode a command still running at the limit is "
        "terminated."
        if restricted
        else "Seconds to wait for the command to finish before yielding a job_id (max 50); returns as soon as it finishes, so a long wait costs nothing."
    )
    background_help = (
        "Unavailable on macOS foreground mode: background=true is refused "
        "(darwin_background_jobs_unavailable)."
        if restricted
        else "Return at once with a job_id after a 1 s warm-up. Local policy may also auto-background matching commands."
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
                description=wait_help,
            ),
        ] = settings.wait_default_s,
        background: Annotated[
            bool,
            Field(description=background_help),
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

    registered: Callable[..., ToolResult | Awaitable[ToolResult]] = run_command
    description = None
    if isinstance(backend, DarwinManagerCommandBackend):
        description = darwin_manager_description(run_command.__doc__)
    if isinstance(backend, RestrictedCommandBackend):
        description = (
            (
                f"Foreground only on macOS, up to {settings.wait_max_s} seconds. "
                if backend.release_states.get("run_command") == "LIMITED"
                else "Foreground execution is unavailable on macOS. "
            )
            + "Background processes are terminated when the command finishes. "
            "Processes that start a new session (setsid) are not tracked. "
            "New sessions/process groups are not tracked or terminated. "
            "Results disclose descendants_unverified=true. "
            "job_status history is in-memory only. "
            "stop_job is unavailable."
        )

        @wraps(run_command)
        async def native_run_command(*args, **kwargs):
            return await run_native_command_impl(
                *args,
                **kwargs,
                roots=roots,
                settings=settings,
                backend=backend,
            )

        registered = native_run_command
    mcp.tool(
        registered,
        name="run_command",
        description=description,
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "openWorldHint": True,
        },
        output_schema=OUTPUT_SCHEMA,
    )


async def run_native_command_impl(
    command: str,
    workdir: str = "~/Projects",
    wait_seconds: int = 1,
    background: bool = False,
    stdin: str | None = None,
    tail_lines: int | None = None,
    *,
    roots: RootsSettings,
    settings: RunCommandSettings,
    backend: RestrictedCommandBackend,
) -> ToolResult:
    """Prepared foreground mapping, inaccessible to the unreviewed default backend."""
    try:
        require_command_available(backend)
        if background:
            raise CommandFailure("darwin_background_jobs_unavailable")
        if backend.foreground_execution is None:
            raise CommandFailure(
                "native_capability_unavailable: foreground provider missing"
            )
        # This branch is reachable only with a reviewed, explicitly injected
        # backend. The production restricted backend refuses before path access.
        resolved = resolve_path(workdir, roots=roots)
        if not resolved.is_dir():
            raise CommandFailure("workdir_not_directory")
        request = ForegroundRequest(
            command,
            resolved,
            stdin,
            wait_seconds,
            background,
            settings.wait_max_s,
            max(1, backend.max_output_chars * 4),
        )
        result = await command_execution.run_foreground_async(
            backend.foreground_execution, request
        )
        if result.exit_code is None and result.signal is None:
            raise CommandFailure("darwin_foreground_completion_unknown")
    except CommandFailure as exc:
        raise ToolError(str(exc)) from exc
    reply = command_execution.foreground_reply(
        result, max_output_chars=backend.max_output_chars, tail_lines=tail_lines
    )
    return ToolResult(content=reply.summary, structured_content=reply.payload)
