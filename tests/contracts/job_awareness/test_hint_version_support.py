"""Execution-witness carrier for fixed, isolated synthetic registrations."""

from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware
from fastmcp.tools.base import ToolResult

from binnacle.mcp.job_awareness_hint import HintAdapter, witnessed_call


class ExecutionCarrier(Middleware):
    """Pass the receipt of the tool body that actually ran to the adapter.

    ADV-G4-01: the carrier never looks a producer up by name, version or
    registry. It runs dispatch through witnessed_call, which issues a receipt
    for the returned result only when exactly one witnessed body completed on
    this server. Native
    dispatch (injection, mounted providers, transforms, version selection)
    decides which body runs. The adapter, not this carrier, decides identity;
    no receipt suppresses (fail closed).
    """

    def __init__(
        self, app: FastMCP, adapter: HintAdapter, seen: list[ToolResult]
    ) -> None:
        self.app, self.adapter, self.seen = app, adapter, seen
        self.adapted: list[ToolResult] = []

    async def on_call_tool(self, context, call_next):
        value, execution = await witnessed_call(call_next, context)
        self.seen.append(value)
        result = await HintAdapter.adapt(self.adapter, value, execution=execution)
        self.adapted.append(result)
        return result
