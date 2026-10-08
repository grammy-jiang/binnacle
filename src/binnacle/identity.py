"""Compatibility alias for MCP-owned identity."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.mcp.identity import *
    from binnacle.mcp.identity import (
        _REMEMBERED_SESSIONS as _REMEMBERED_SESSIONS,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.mcp import identity as _impl

    sys.modules[__name__] = _impl
