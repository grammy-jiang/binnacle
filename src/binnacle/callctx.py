"""Compatibility alias for MCP-owned callctx."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.mcp.callctx import *
else:
    import sys

    from binnacle.mcp import callctx as _impl

    sys.modules[__name__] = _impl
