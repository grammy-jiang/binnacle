"""Compatibility alias to the feature-owned Commands MCP adapter."""

import sys as _sys

from binnacle.features.commands.tools import run_command as _implementation
from binnacle.features.commands.tools.run_command import register, run_command_impl

__all__ = ["register", "run_command_impl"]

_sys.modules[__name__] = _implementation
