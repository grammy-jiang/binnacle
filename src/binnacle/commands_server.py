"""Focused Commands server using the existing durable-job MCP adapters."""

from fastmcp import FastMCP

from binnacle.tools import job_status, run_command, stop_job


def create_commands_server() -> FastMCP:
    """Build an independent Commands child for native FastMCP composition."""
    commands = FastMCP("binnacle-commands", on_duplicate="error")
    run_command.register(commands)
    job_status.register(commands)
    stop_job.register(commands)
    return commands
