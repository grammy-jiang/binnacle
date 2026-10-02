"""binnacle's MCP tools — one module per tool, mirroring docs/tools/<name>.md."""

from fastmcp import FastMCP

from . import (
    job_status,
    run_command,
    search_text,
    stop_job,
)


def register_all(mcp: FastMCP) -> None:
    search_text.register(mcp)
    run_command.register(mcp)
    job_status.register(mcp)
    stop_job.register(mcp)
