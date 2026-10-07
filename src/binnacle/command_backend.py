"""Compatibility API for the relocated Commands backend selection."""

from binnacle.features.commands.command_backend import (
    DurableCommandBackend,
    create_command_backend,
)

__all__ = ["DurableCommandBackend", "create_command_backend"]
