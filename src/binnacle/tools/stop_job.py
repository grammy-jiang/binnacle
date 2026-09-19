"""stop_job — stop a background job (SIGTERM, then SIGKILL after 5 s).

Spec: docs/tools/run_command.md §5. Signals the whole process group so
children die too (Copilot's "whole process tree" lesson).
"""

from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools.base import ToolResult
from pydantic import Field

from binnacle import jobs

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


def stop_job_impl(job_id: str) -> ToolResult:
    result = jobs.stop_job(job_id)
    if result is None:
        raise ToolError(
            f"No job with id {job_id!r}. Call job_status without a job_id to list recent jobs."
        )
    payload = {
        "job_id": job_id,
        "state": result["state"],
        "exit_code": result["exit_code"],
        "signal": result["signal"],
    }
    if result["state"] == "exited":
        if result["signal"] is not None:
            summary = f"Job {job_id} stopped (signal {result['signal']})."
        else:
            summary = f"Job {job_id} already exited {result['exit_code']}."
    else:
        summary = f"Job {job_id} is in state {result['state']}."
    return ToolResult(content=summary, structured_content=payload)


def register(mcp: FastMCP) -> None:
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
        return stop_job_impl(job_id)
