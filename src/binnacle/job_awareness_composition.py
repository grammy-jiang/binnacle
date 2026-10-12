"""Production composition of Job Awareness hints (default off).

``binnacle.application`` imports this module only when
``settings.job_awareness.hints_enabled`` is true. It joins the reviewed core
route (``session_route``: parser and in-memory HMAC epoch keyer;
``session_fence``: per-key asyncio fence) with the MCP carrier
(``binnacle.mcp.job_awareness_live``). ``binnacle.mcp`` may not import
``binnacle.features`` (top-level acyclic contract), so the parser and the
fence are injected here.

No E2 lab module (``session_lab``, the lab ledger, serving, snapshot or
emission modules, the lab extraction ``job_awareness_session``, the
synthetic adapter or the lab server) is imported; the import-linter contract
``job-awareness-live-no-lab`` keeps it so.
"""

from __future__ import annotations

import logging
import secrets
from functools import partial

from fastmcp import FastMCP

from binnacle.config import Settings
from binnacle.features.commands.command_contracts import CommandBackend
from binnacle.features.commands.job_awareness.session_fence import FenceSet
from binnacle.features.commands.job_awareness.session_route import (
    SessionKeyer,
    route,
)
from binnacle.mcp.identity import ClientIdentity
from binnacle.mcp.job_awareness_live import JobAwarenessHints

__all__ = ["FENCE_TIMEOUT_S", "install_job_awareness"]

logger = logging.getLogger("binnacle.job_awareness")

#: A call waits at most this long for its conversation's fence; then the
#: result returns unchanged (``reason=busy``) and the jobs stay pending.
FENCE_TIMEOUT_S = 5.0


def install_job_awareness(
    root: FastMCP,
    *,
    settings: Settings,
    backend: CommandBackend,
    identity: ClientIdentity,
) -> JobAwarenessHints:
    """Add the hint middleware to ``root``; call it after the policy middleware.

    A fresh epoch key per application generation: a restart forgets every
    binding, so no job from an earlier process is ever hinted.
    """
    keyer = SessionKeyer(secrets.token_hex(16))
    middleware = JobAwarenessHints(
        classify=partial(route, keyer),
        fences=FenceSet(FENCE_TIMEOUT_S),
        identity=identity,
        client_names=tuple(settings.job_awareness.client_names),
        job_state=backend.job_state,
        server=root,
    )
    root.add_middleware(middleware)
    logger.info(
        "event=job_awareness_config hints_enabled=true clients=%d carrier=struct",
        len(settings.job_awareness.client_names),
    )
    return middleware
