"""Dormant all-tools admission and bounded drain, not a production lease.

No FastMCP application installs this middleware automatically. Only an
authorized, separate controller could eventually initiate pause; this
proof-of-behavior has no IPC endpoint or user-facing control action.

A closed generation stays closed until the server process exits. Its
in-memory drain is never evidence that durable jobs, transport sessions or
other application generations are quiet.
"""

from __future__ import annotations

import math
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

_NONCE = re.compile(r"^[0-9a-f]{32}$")


class ToolAdmissionPaused(RuntimeError):
    """New MCP tool calls are not admitted after this generation is fenced."""


class ToolAdmissionUnknown(RuntimeError):
    """A forged or unexpected close/release cannot be treated as drained."""


@dataclass(frozen=True)
class AdmissionTicket:
    """Opaque lifetime token for exactly one accepted tools/call."""

    generation: str
    sequence: int


@dataclass(frozen=True)
class DrainSnapshot:
    generation: str
    pause_nonce: str | None
    in_flight: int
    drained: bool
    shutdown_authorized: bool = False

    def __post_init__(self) -> None:
        if self.shutdown_authorized:
            raise ValueError("in-memory drain never authorizes producer stop")


class ToolAdmissionDrain:
    """A linearizable local process gate for native FastMCP tools/call.

    A manager/backend must have its OWN admission fence. This does not
    terminate already accepted calls or extend authority across processes.
    """

    def __init__(self) -> None:
        self.generation = uuid.uuid4().hex
        self._cond = threading.Condition()
        self._next = 0
        self._active: set[int] = set()
        self._pause_nonce: str | None = None

    def _snapshot(self) -> DrainSnapshot:
        return DrainSnapshot(
            self.generation,
            self._pause_nonce,
            len(self._active),
            self._pause_nonce is not None and not self._active,
        )

    def snapshot(self) -> DrainSnapshot:
        with self._cond:
            return self._snapshot()

    def admit(self) -> AdmissionTicket:
        with self._cond:
            if self._pause_nonce is not None:
                raise ToolAdmissionPaused("MCP tools temporarily unavailable")
            self._next += 1
            self._active.add(self._next)
            return AdmissionTicket(self.generation, self._next)

    def release(self, ticket: AdmissionTicket) -> None:
        with self._cond:
            if (
                not isinstance(ticket, AdmissionTicket)
                or ticket.generation != self.generation
                or type(ticket.sequence) is not int
                or ticket.sequence not in self._active
            ):
                raise ToolAdmissionUnknown("MCP call ownership unprovable")
            self._active.remove(ticket.sequence)
            self._cond.notify_all()

    def fence(self, *, nonce: str, generation: str) -> DrainSnapshot:
        """Forever refuse future tools/call on THIS generation."""
        if not isinstance(nonce, str) or _NONCE.fullmatch(nonce) is None:
            raise ToolAdmissionUnknown("invalid maintenance transaction nonce")
        with self._cond:
            if generation != self.generation:
                raise ToolAdmissionUnknown("MCP generation rotated")
            if self._pause_nonce is not None and self._pause_nonce != nonce:
                raise ToolAdmissionUnknown("another transaction closed MCP admission")
            self._pause_nonce = nonce
            self._cond.notify_all()
            return self._snapshot()

    def wait_drained(self, *, nonce: str, timeout: float) -> DrainSnapshot:
        """Wait boundedly for accepted tool calls, not durable jobs or HTTP."""
        if (
            not isinstance(timeout, (float, int))
            or isinstance(timeout, bool)
            or not math.isfinite(timeout)
            or not 0 <= timeout <= 120
        ):
            raise ToolAdmissionUnknown("invalid drain wait timeout")
        deadline = time.monotonic() + timeout
        with self._cond:
            if self._pause_nonce != nonce or self._pause_nonce is None:
                raise ToolAdmissionUnknown("MCP drain transaction not owned")
            while self._active:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self._cond.wait(timeout=left)
            return self._snapshot()


class ToolAdmissionDrainMiddleware(Middleware):
    """Dormant FastMCP adapter with correct BaseException/cancel cleanup.

    Not attached by create_application. Tests can compose this on a private
    synthetic application; a production controller is a separate project.
    """

    def __init__(self, gate: ToolAdmissionDrain) -> None:
        self.gate = gate

    async def on_call_tool(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        try:
            ticket = self.gate.admit()
        except ToolAdmissionPaused as exc:
            raise ToolError(
                "MCP maintenance: new tool calls temporarily refused"
            ) from exc
        try:
            return await call_next(context)
        finally:
            self.gate.release(ticket)
