"""Compatibility alias for MCP-owned visibility."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.mcp.visibility import *
else:
    import sys

    from binnacle.mcp import visibility as _impl

    sys.modules[__name__] = _impl
