"""Opt-in MCP-request-wide admission fence for a real FastMCP generation.

Unlike the older tool-only middleware this catches all externally submitted
MCP *requests*, including tool/resource/prompt/list/initialize operations.
Notifications are not actions and are not held here, so cancel/shutdown
messages can still flow. The gate never stops, restarts or prunes a service.
It only releases an admitted call after its coroutine actually completes.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import (
    CallNext,
    Middleware,
    MiddlewareContext,
)
from mcp.shared.exceptions import MCPError

from binnacle.mcp.tool_admission_drain import (
    AdmissionTicket,
    ToolAdmissionDrain,
    ToolAdmissionPaused,
)

_REQUEST_TICKET: ContextVar[AdmissionTicket | None] = ContextVar(
    "binnacle_maintenance_mcp_request_ticket", default=None
)


class FullRequestAdmissionMiddleware(Middleware):
    """Optional single-generation gate, never installed without explicit opt-in.

    Do not reject a previously admitted in-flight tool call when the external
    controller starts its fence between request entry and typed dispatch.
    A ContextVar inherited through this request ensures exactly one ticket
    across the outer/typed middleware phases; internal typed-only calls still
    get their own admission ticket. Fenced requests fail before downstream
    tool side effects and every exception/cancellation releases exactly once.
    """

    def __init__(self, gate: ToolAdmissionDrain) -> None:
        self.gate = gate

    async def _admit(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
        *,
        request_level: bool = False,
    ) -> Any:
        existing = _REQUEST_TICKET.get()
        if existing is not None and existing.generation == self.gate.generation:
            return await call_next(context)
        try:
            ticket = self.gate.admit()
        except ToolAdmissionPaused as exc:
            if request_level:
                # Whole-MCP request paths must return a JSON-RPC error rather
                # than an internal-server error; typed tool calls retain
                # their ordinary ToolError semantics.
                raise MCPError(
                    -32000, "Binnacle maintenance: request admission closed"
                ) from exc
            raise ToolError("Binnacle maintenance: request admission closed") from exc
        state = _REQUEST_TICKET.set(ticket)
        try:
            return await call_next(context)
        finally:
            _REQUEST_TICKET.reset(state)
            self.gate.release(ticket)

    async def on_request(
        self, context: MiddlewareContext[Any], call_next: CallNext[Any, Any]
    ) -> Any:
        return await self._admit(context, call_next, request_level=True)

    async def on_call_tool(
        self, context: MiddlewareContext[Any], call_next: CallNext[Any, Any]
    ) -> Any:
        # Direct typed-only dispatch (e.g. FastMCP delegation, internal Client)
        # may not have passed through the outer request hook.
        return await self._admit(context, call_next)
