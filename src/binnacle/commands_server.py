"""Focused Commands server using the existing durable-job MCP adapters."""

from fastmcp import FastMCP

from binnacle.command_backend import create_command_backend
from binnacle.command_contracts import CommandBackend
from binnacle.config import RootsSettings, RunCommandSettings, get_settings
from binnacle.tools import job_status, run_command, stop_job


def create_commands_server(
    *,
    backend: CommandBackend | None = None,
    roots: RootsSettings | None = None,
    run_settings: RunCommandSettings | None = None,
    quiet_after_s: int | None = None,
    listing_history_limit: int | None = None,
    listing_command_preview_chars: int | None = None,
) -> FastMCP:
    """Build an independent Commands child for native FastMCP composition."""
    if (
        roots is None
        or run_settings is None
        or quiet_after_s is None
        or listing_history_limit is None
        or listing_command_preview_chars is None
    ):
        defaults = get_settings()
        roots = defaults.roots if roots is None else roots
        run_settings = defaults.run_command if run_settings is None else run_settings
        quiet_after_s = (
            defaults.jobs.quiet_after_s if quiet_after_s is None else quiet_after_s
        )
        listing_history_limit = (
            defaults.jobs.listing_history_limit
            if listing_history_limit is None
            else listing_history_limit
        )
        listing_command_preview_chars = (
            defaults.jobs.listing_command_preview_chars
            if listing_command_preview_chars is None
            else listing_command_preview_chars
        )
    roots, run_settings = (
        roots.model_copy(deep=True),
        run_settings.model_copy(deep=True),
    )
    backend = create_command_backend() if backend is None else backend
    commands = FastMCP("binnacle-commands", on_duplicate="error")
    run_command.register(commands, roots=roots, settings=run_settings, backend=backend)
    job_status.register(
        commands,
        backend=backend,
        quiet_after_s=quiet_after_s,
        history_limit=listing_history_limit,
        preview_chars=listing_command_preview_chars,
        wait_max=run_settings.wait_max_s,
    )
    stop_job.register(commands, backend=backend)
    return commands
