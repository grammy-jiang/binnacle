"""Request-local session-route extraction for one ``tools/call``.

Moved unchanged from the E2 lab module ``job_awareness_session`` so that the
production Job Awareness composition can use the reviewed extraction without
importing a lab module. The lab module re-exports these names, so both paths
run the same function object.

Inputs (E2 design §2.1). For one ``tools/call``, the raw header values of
``x-openai-session`` and ``x-openai-subject`` come from ``headers.getlist()``
of the HTTP request that the FastMCP request context holds, and the two
``_meta`` values come from the same call's raw ``params._meta``. Nothing else
is an identity input: tool arguments, ``clientInfo``, ``Mcp-Session-Id`` and
``X-Request-Id`` are never read here. The values pass straight into the
injected core parser (``functools.partial(session_route.route, keyer)``),
which returns digests only. This module never stores, logs, returns or
formats a raw value.

Import boundary. ``binnacle.mcp`` may not import ``binnacle.features`` (the
top-level acyclic contract), so the parser is injected.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TypeVar

from fastmcp.server.dependencies import fastmcp_request_ctx

__all__ = [
    "RAW_VALUE",
    "SESSION_HEADER",
    "SUBJECT_HEADER",
    "Classifier",
    "route_call",
]

#: Mirrors of the core ``session_route`` names (pinned equal by a contract test).
SESSION_HEADER = "x-openai-session"
SUBJECT_HEADER = "x-openai-subject"
#: Every export, log and argument log is scanned for this (design §2.7).
RAW_VALUE = re.compile(r"v1/[A-Za-z0-9_-]{40,}")
R = TypeVar("R")
#: ``(session header values, subject header values, raw _meta or None)``.
Classifier = Callable[[list[str], list[str], "dict[str, object] | None"], R]


def route_call(classify: Classifier[R]) -> R:
    """Classify the current ``tools/call`` from its own request only.

    ``classify`` is the core parser bound to the epoch keyer. It receives the
    raw values once and returns a digest-only outcome.

    Call it inside the ``tools/call`` handler (for example from a middleware
    ``on_call_tool``). ``getlist`` keeps duplicate header lines and matches
    names case-insensitively. Without a bound request context or an HTTP
    request (in-memory transport), both header lists are empty and the parser
    returns ``NO_SESSION``. A non-dict ``_meta`` is absent (``NO_META``);
    non-string ``_meta`` values reach the parser untouched and fail closed
    there. The outcome holds digests only; raw values do not outlive this call.
    """
    context = fastmcp_request_ctx.get()
    request = None if context is None else context.request
    if context is None or request is None:
        return classify([], [], None)
    headers = request.headers
    meta = context.meta
    return classify(
        headers.getlist(SESSION_HEADER),
        headers.getlist(SUBJECT_HEADER),
        meta if type(meta) is dict else None,
    )
