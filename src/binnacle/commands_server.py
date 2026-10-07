"""Compatibility module alias for the G6 Commands child."""

import sys as _sys

from binnacle.features.commands import commands_server as _implementation
from binnacle.features.commands.commands_server import create_commands_server

__all__ = ["create_commands_server"]

_sys.modules[__name__] = _implementation
