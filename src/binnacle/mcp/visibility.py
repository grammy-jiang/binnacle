"""Per-client policy with native FastMCP component visibility.

Serves each configured client exactly the tools enabled for it, while
every other client gets the full surface. Which client sees what is data,
not code: ``Settings.client_tools`` maps a client-name *prefix* to the
tool names that client is served (an allowlist -- a new tool must be
added to a client's list before that client sees it).

Client identity comes from the shared :class:`binnacle.mcp.identity.ClientIdentity`
resolver; see that module for the per-era details.
"""

from collections.abc import Sequence

from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_context
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.server.transforms import GetToolNext, Transform, Visibility
from fastmcp.tools.base import Tool
from fastmcp.utilities.versions import VersionSpec

from binnacle.mcp.identity import ClientIdentity


class ClientToolVisibility(Middleware):
    def __init__(
        self,
        client_tools: dict[str, tuple[str, ...]],
        identity: ClientIdentity | None = None,
    ) -> None:
        self._enabled = {
            prefix: frozenset(tools) for prefix, tools in client_tools.items()
        }
        self._identity = identity or ClientIdentity()

    def _enabled_for(self, client_name: str | None) -> frozenset[str] | None:
        """The allowlist for this client, or None meaning unrestricted."""
        if client_name:
            for prefix, tools in self._enabled.items():
                if client_name.startswith(prefix):
                    return tools
        return None

    async def on_discover(self, context: MiddlewareContext, call_next: CallNext):
        # Resolving here remembers the _meta identity for the bare
        # follow-up requests of the same session.
        self._identity.resolve(context)
        return await call_next(context)

    async def _publish(self, context: MiddlewareContext) -> frozenset[str] | None:
        enabled = self._enabled_for(self._identity.resolve(context))
        ctx = context.fastmcp_context
        if ctx is not None and ctx.request_context is not None:
            await ctx.set_state(_ALLOWLIST_KEY, enabled, serializable=False)
        return enabled

    async def on_list_tools(self, context: MiddlewareContext, call_next: CallNext):
        await self._publish(context)
        return await call_next(context)

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext):
        enabled = await self._publish(context)
        name = getattr(context.message, "name", None)
        if enabled is not None and name not in enabled:
            raise ToolError(f"Tool {name!r} is not available to this client.")
        return await call_next(context)


_ALLOWLIST_KEY = "binnacle.client_tool_allowlist"


def _request_context() -> Context | None:
    """Direct Python introspection has no protocol policy or session state."""
    try:
        ctx = get_context()
    except RuntimeError as exc:
        if str(exc) != "No active context found.":
            raise
        return None
    return ctx if ctx.request_context is not None else None


class ClientToolVisibilityTransform(Transform):
    """Delegate request policy marking to native Visibility; keep no client state."""

    async def _allowlist(self) -> frozenset[str] | None:
        ctx = _request_context()
        return await ctx.get_state(_ALLOWLIST_KEY) if ctx is not None else None

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        allowed = await self._allowlist()
        if allowed is None:
            return tools
        marked = await Visibility(False, components={"tool"}).list_tools(tools)
        return await Visibility(
            True, names=set(allowed), components={"tool"}
        ).list_tools(marked)

    async def get_tool(
        self, name: str, call_next: GetToolNext, *, version: VersionSpec | None = None
    ) -> Tool | None:
        allowed = await self._allowlist()
        if allowed is None:
            return await call_next(name, version=version)
        return await Visibility(name in allowed, components={"tool"}).get_tool(
            name, call_next, version=version
        )
