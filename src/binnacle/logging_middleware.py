"""Compatibility alias for MCP-owned logging_middleware."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.mcp.logging_middleware import *
    from binnacle.mcp.logging_middleware import (
        _base_turn as _base_turn,  # noqa: PLC0414
    )
    from binnacle.mcp.logging_middleware import (
        _header_fields as _header_fields,  # noqa: PLC0414
    )
    from binnacle.mcp.logging_middleware import (
        _result_fields as _result_fields,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.mcp import logging_middleware as _impl

    sys.modules[__name__] = _impl
