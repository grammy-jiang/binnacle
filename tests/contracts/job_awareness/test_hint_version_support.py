"""Native producer resolution for fixed, isolated synthetic registrations."""

from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware
from fastmcp.tools.base import ToolResult
from fastmcp.utilities.versions import VersionSpec

from binnacle.mcp.job_awareness_hint import HintAdapter


class VersionBoundCarrier(Middleware):
    """Use native selection, including highest-version and unversioned fallback.

    This lab has fixed registrations and no downstream middleware that rewrites
    routing or substitutes results. The resolved tool is the actual producer.
    """

    def __init__(
        self, app: FastMCP, adapter: HintAdapter, seen: list[ToolResult]
    ) -> None:
        self.app, self.adapter, self.seen = app, adapter, seen
        self.adapted: list[ToolResult] = []

    async def on_call_tool(self, context, call_next):
        # FastMCP constructs this metadata from its dispatch VersionSpec.
        selector = (context.message.meta or {}).get("fastmcp", {}).get("version")
        version = (
            VersionSpec(eq=selector)
            if isinstance(selector, str)
            else VersionSpec(**selector)
            if isinstance(selector, dict)
            else None
        )
        producer = await self.app.get_tool(context.message.name, version=version)
        value = await call_next(context)
        self.seen.append(value)
        result = (
            value
            if producer is None
            else await HintAdapter.adapt(
                self.adapter,
                value,
                tool_name=producer.name,
                tool_version=producer.version,
            )
        )
        self.adapted.append(result)
        return result
