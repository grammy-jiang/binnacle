"""stop_job — stop a background job (SIGTERM, then SIGKILL after 5 s).

Spec: docs/tools/run_command.md §5. Signals the whole process group so
children die too (Copilot's "whole process tree" lesson).
"""

from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools.base import ToolResult
from pydantic import Field

from binnacle.features.commands import command_execution
from binnacle.features.commands.command_backend import create_command_backend
from binnacle.features.commands.command_contracts import CommandBackend, CommandFailure

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "job_id": {"type": "string"},
        "state": {"type": "string"},
        "exit_code": {"type": ["integer", "null"]},
        "signal": {"type": ["integer", "null"]},
    },
    "required": ["job_id", "state"],
}


def stop_job_impl(job_id: str, *, backend: CommandBackend | None = None) -> ToolResult:
    backend = create_command_backend() if backend is None else backend
    try:
        reply = command_execution.stop_job(job_id, backend=backend)
    except CommandFailure as exc:
        raise ToolError(str(exc)) from exc.__cause__
    return ToolResult(content=reply.summary, structured_content=reply.payload)


def register(mcp: FastMCP, *, backend: CommandBackend | None = None) -> None:
    backend = create_command_backend() if backend is None else backend

    @mcp.tool(
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        output_schema=OUTPUT_SCHEMA,
    )
    def stop_job(
        job_id: Annotated[str, Field(description="Job to stop.")],
    ) -> ToolResult:
        """Stop a job (SIGTERM, then SIGKILL after 5 s) and its whole
        process group. An already-finished job returns its final state
        without error.
        """
        return stop_job_impl(job_id, backend=backend)
