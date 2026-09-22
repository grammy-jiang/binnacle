"""Stable telemetry codes for user-facing MCP tool errors."""

from fastmcp.exceptions import ToolError


class CodedToolError(ToolError):
    """A normal ToolError carrying a stable low-cardinality telemetry code."""

    def __init__(self, code: str, message: str) -> None:
        self.telemetry_code = code
        super().__init__(message)
