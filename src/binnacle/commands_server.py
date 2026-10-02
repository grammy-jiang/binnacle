"""Focused Commands server using the existing durable-job MCP adapters."""

from fastmcp import FastMCP

from binnacle.config import RootsSettings, RunCommandSettings, get_settings
from binnacle.tools import job_status, run_command, stop_job


def create_commands_server(
    *,
    roots: RootsSettings | None = None,
    run_settings: RunCommandSettings | None = None,
) -> FastMCP:
    """Build an independent Commands child for native FastMCP composition."""
    if roots is None or run_settings is None:
        defaults = get_settings()
        roots = defaults.roots if roots is None else roots
        run_settings = defaults.run_command if run_settings is None else run_settings
    commands = FastMCP("binnacle-commands", on_duplicate="error")
    run_command.register(commands, roots=roots, settings=run_settings)
    job_status.register(commands)
    stop_job.register(commands)
    return commands
