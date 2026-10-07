"""Compatibility alias to the feature-owned Commands MCP adapter."""

import sys as _sys

from binnacle.features.commands.tools import job_status as _implementation
from binnacle.features.commands.tools.job_status import job_status_impl, register

__all__ = ["job_status_impl", "register"]

_sys.modules[__name__] = _implementation
