"""Per-client tool visibility (middleware).

Serves each configured client exactly the tools enabled for it, while
every other client gets the full surface. Which client sees what is data,
not code: ``Settings.client_tools`` maps a client-name *prefix* to the
tool names that client is served (an allowlist -- a new tool must be
added to a client's list before that client sees it).

Client identity comes from the shared :class:`binnacle.identity.ClientIdentity`
resolver; see that module for the per-era details.
"""

from collections.abc import Sequence

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from binnacle.identity import ClientIdentity


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

    async def on_list_tools(self, context: MiddlewareContext, call_next: CallNext):
        tools: Sequence = await call_next(context)
        enabled = self._enabled_for(self._identity.resolve(context))
        if enabled is None:
            return tools
        return [t for t in tools if t.name in enabled]

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext):
        enabled = self._enabled_for(self._identity.resolve(context))
        name = getattr(context.message, "name", None)
        if enabled is not None and name not in enabled:
            raise ToolError(f"Tool {name!r} is not available to this client.")
        return await call_next(context)
