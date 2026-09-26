"""binnacle's MCP tools — one module per tool, mirroring docs/tools/<name>.md."""

from fastmcp import FastMCP

from . import (
    edit_file,
    job_status,
    list_files,
    read_file,
    read_files,
    run_command,
    search_text,
    stop_job,
    write_file,
)


def register_all(mcp: FastMCP) -> None:
    read_file.register(mcp)
    read_files.register(mcp)  # only in read_file.multi_mode "tool"
    list_files.register(mcp)
    search_text.register(mcp)
    edit_file.register(mcp)
    write_file.register(mcp)
    run_command.register(mcp)
    job_status.register(mcp)
    stop_job.register(mcp)
