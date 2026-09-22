"""Temporary read-only tools for the ChatGPT async-orchestration experiment.

These tools are isolated to the experiment branch and must not be merged into
the production tool surface.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Annotated, Protocol

from fastmcp import FastMCP
from fastmcp.server.context import Context
from fastmcp.tools.base import ToolResult
from pydantic import Field

from binnacle.callctx import current_call

TASKS_EXTENSION = "io.modelcontextprotocol/tasks"
log = logging.getLogger("binnacle.async_probe")


class _ExtensionContext(Protocol):
    def client_supports_extension(self, extension_id: str) -> bool: ...

    def client_extension_settings(self, identifier: str) -> dict | None: ...


def _event(
    phase: str,
    tool: str,
    probe_id: str,
    *,
    label: str = "-",
    token: str = "-",
) -> None:
    log.info(
        "event=async_probe phase=%s tool=%s probe_id=%s label=%s token=%s "
        "call=%s monotonic_ns=%d",
        phase,
        tool,
        probe_id,
        label,
        token,
        current_call.get(),
        time.monotonic_ns(),
    )


def capabilities_payload(ctx: _ExtensionContext) -> dict:
    per_request = ctx.client_extension_settings(TASKS_EXTENSION)
    protocol_version = None
    client_name = None
    try:
        params = ctx.session.client_params  # type: ignore[attr-defined]
        if params is not None:
            protocol_version = str(params.protocol_version)
            client_name = params.client_info.name
    except (AttributeError, RuntimeError):
        pass
    return {
        "tasks_initialize_capability": ctx.client_supports_extension(TASKS_EXTENSION),
        "tasks_request_capability": per_request is not None,
        "tasks_request_settings": per_request,
        "protocol_version": protocol_version,
        "client_name": client_name,
    }


async def wait_impl(probe_id: str, label: str, delay_s: float) -> ToolResult:
    _event("start", "wait", probe_id, label=label)
    started = time.monotonic()
    await asyncio.sleep(delay_s)
    elapsed = time.monotonic() - started
    _event("end", "wait", probe_id, label=label)
    payload = {
        "probe_id": probe_id,
        "label": label,
        "delay_s": delay_s,
        "elapsed_s": round(elapsed, 3),
    }
    return ToolResult(
        content=f"Probe {probe_id}/{label} completed after {elapsed:.3f} s.",
        structured_content=payload,
    )


async def seed_impl(probe_id: str, delay_s: float = 0.0) -> ToolResult:
    token = uuid.uuid4().hex
    _event("start", "seed", probe_id, token=token)
    if delay_s:
        await asyncio.sleep(delay_s)
    payload = {"probe_id": probe_id, "token": token, "delay_s": delay_s}
    _event("end", "seed", probe_id, token=token)
    return ToolResult(content=token, structured_content=payload)


def echo_impl(probe_id: str, token: str) -> ToolResult:
    _event("start", "echo", probe_id, token=token)
    payload = {"probe_id": probe_id, "token": token}
    _event("end", "echo", probe_id, token=token)
    return ToolResult(content=token, structured_content=payload)


PROBE_ID = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
        description="Unique experiment id shared by calls in one trial.",
    ),
]


def register(mcp: FastMCP) -> None:
    annotations = {"readOnlyHint": True, "openWorldHint": False}

    @mcp.tool(annotations=annotations)
    async def async_probe_capabilities(probe_id: PROBE_ID, ctx: Context) -> dict:
        """Report whether this live MCP request advertises the MCP Tasks extension."""
        _event("start", "capabilities", probe_id)
        payload = {"probe_id": probe_id, **capabilities_payload(ctx)}
        _event("end", "capabilities", probe_id)
        return payload

    @mcp.tool(annotations=annotations)
    async def async_probe_wait(
        probe_id: PROBE_ID,
        label: Annotated[
            str,
            Field(
                min_length=1,
                max_length=32,
                pattern=r"^[A-Za-z0-9._-]+$",
                description="Short label distinguishing waits in the same trial.",
            ),
        ],
        delay_s: Annotated[
            float,
            Field(
                ge=0.1,
                le=20.0,
                description="Seconds to keep this MCP call unresolved (max 20).",
            ),
        ],
    ) -> ToolResult:
        """Hold one read-only MCP call open for a controlled scheduling probe."""
        return await wait_impl(probe_id, label, delay_s)

    @mcp.tool(annotations=annotations)
    async def async_probe_seed(
        probe_id: PROBE_ID,
        delay_s: Annotated[
            float,
            Field(
                ge=0.0,
                le=5.0,
                description="Optional delay before returning the unpredictable token.",
            ),
        ] = 0.0,
    ) -> ToolResult:
        """Return an unpredictable token for a causal async-scheduling probe."""
        return await seed_impl(probe_id, delay_s)

    @mcp.tool(annotations=annotations)
    def async_probe_echo(
        probe_id: PROBE_ID,
        token: Annotated[
            str,
            Field(
                min_length=32,
                max_length=64,
                description="Exact token returned by async_probe_seed.",
            ),
        ],
    ) -> ToolResult:
        """Echo the exact seed token; call only after receiving async_probe_seed."""
        return echo_impl(probe_id, token)
