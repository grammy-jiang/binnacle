"""Compatibility alias for MCP-owned tool_order."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.mcp.tool_order import *
else:
    import sys

    from binnacle.mcp import tool_order as _impl

    sys.modules[__name__] = _impl
