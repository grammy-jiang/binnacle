"""Compatibility alias to the feature-owned Commands MCP adapter."""

import sys as _sys

from binnacle.features.commands.tools import stop_job as _implementation
from binnacle.features.commands.tools.stop_job import register, stop_job_impl

__all__ = ["register", "stop_job_impl"]

_sys.modules[__name__] = _implementation
