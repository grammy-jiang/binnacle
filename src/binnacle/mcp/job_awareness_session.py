"""E2 lab: MCP-side session-route extraction and digest-only log fields.

LAB_ONLY and default off. No production composition imports this module; the
synthetic E2 lab server (S7) and the contract tests are its only callers.

Inputs (design §2.1). For one ``tools/call``, the raw header values of
``x-openai-session`` and ``x-openai-subject`` come from
``headers.getlist()`` of the HTTP request that ``get_http_request()`` returns,
and the two ``_meta`` values come from the same call's raw ``params._meta``.
Both are read from the one FastMCP request context that the ``tools/call``
handler binds (``fastmcp_request_ctx``): its ``request`` is the object
``get_http_request()`` returns first, and its ``meta`` is the raw ``_meta``
block of the same params. ``context.message.meta`` of a FastMCP middleware is
not used: FastMCP 4.1 rebuilds that message and drops the client ``_meta``.
Nothing else is an identity input:
tool arguments, ``clientInfo``, ``Mcp-Session-Id`` and ``X-Request-Id`` are
never read here. The values pass straight into the injected core parser
(``functools.partial(session_route.route, keyer)``), which returns digests
only. This module never stores, logs, returns or formats a raw value.

Import boundary. ``binnacle.mcp`` may not import ``binnacle.features`` (the
top-level acyclic contract), so the parser is injected and the outcome is
read structurally: its status must be one of the fixed ``ROUTE_STATUSES`` and
its log key exactly 16 lowercase hex characters, or no field is produced.

Header handling. Starlette matches header names case-insensitively and keeps
every header line, so duplicates (even equal ones) reach the parser as a list
of two or more and fail closed. Header bytes are decoded as Latin-1 by the
ASGI layer without other normalization, so a non-ASCII byte stays a non-ASCII
character and fails the grammar. Comma-joined values are one value and also
fail the grammar.

Log fields (design §2.7). ``ja_route`` is the route status and ``ja_key`` is
the first 16 hex characters of ``d_sess``. Every emitted field passes a
raw-value scan; a field that looks like a platform value is refused.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from enum import Enum
from typing import Protocol

# The reviewed extraction lives in the production-allowed module; the lab
# re-exports the same objects (one implementation, pinned by a test).
from binnacle.mcp.job_awareness_route import (
    RAW_VALUE,
    SESSION_HEADER,
    SUBJECT_HEADER,
    Classifier,
    route_call,
)

__all__ = [
    "LAB_MARKERS",
    "RAW_VALUE",
    "ROUTE_STATUSES",
    "SESSION_HEADER",
    "SUBJECT_HEADER",
    "Classifier",
    "LabLogError",
    "format_fields",
    "lab_fields",
    "raw_value_hits",
    "route_call",
    "route_fields",
]

ROUTE_STATUSES = frozenset(
    {
        "BOUND",
        "UNBOUND",
        "NO_SESSION",
        "NO_META",
        "MALFORMED",
        "MISMATCH",
        "KEY_FULL",
        "KEY_NAMESPACE",
        "SUSPENDED",
    }
)
#: Harness-only ``ja_lab_marker`` vocabulary (TC-5 N5 scripted replay).
LAB_MARKERS = frozenset({"scripted"})
_FIELD_NAME = re.compile(r"ja_[a-z_]{1,24}|rid|emit_state|grant_remaining_ms")
_FIELD_VALUE = re.compile(r"[A-Za-z0-9_.:,-]{1,128}")
_HANDLE = re.compile(r"j_[0-9a-f]{12}")
_RID = re.compile(r"[0-9a-f]{32}")
_LOG_KEY = re.compile(r"[0-9a-f]{16}")


class LoggedKey(Protocol):
    @property
    def log_key(self) -> str: ...


class LoggedOutcome(Protocol):
    """The read-only view of a core ``RouteOutcome`` that logging needs."""

    @property
    def status(self) -> Enum: ...
    @property
    def key(self) -> LoggedKey | None: ...
    @property
    def format_change(self) -> bool: ...


_EMIT_STATES = frozenset({"PENDING", "RESERVED", "EMITTED", "ABORTED", "-"})


class LabLogError(ValueError):
    """A log field failed validation; the caller logs nothing for it."""


def _checked(name: str, value: str) -> str:
    if (
        type(name) is not str
        or type(value) is not str
        or _FIELD_NAME.fullmatch(name) is None
        or _FIELD_VALUE.fullmatch(value) is None
        or RAW_VALUE.search(value) is not None
    ):
        raise LabLogError(name if type(name) is str else "field")
    return value


def route_fields(outcome: LoggedOutcome) -> dict[str, str]:
    """``ja_route`` and ``ja_key`` (16-hex export prefix) for one call."""
    try:
        status, key, changed = outcome.status, outcome.key, outcome.format_change
        value = status.value if isinstance(status, Enum) else None
        log_key = "-" if key is None else key.log_key
    except AttributeError:
        raise LabLogError("ja_route") from None
    if type(value) is not str or value not in ROUTE_STATUSES:
        raise LabLogError("ja_route")
    if log_key != "-" and (type(log_key) is not str or not _LOG_KEY.fullmatch(log_key)):
        raise LabLogError("ja_key")
    if type(changed) is not bool:
        raise LabLogError("ja_format_change")
    fields = {"ja_route": value, "ja_key": log_key}
    if changed:
        fields["ja_format_change"] = "1"
    return {name: _checked(name, value) for name, value in fields.items()}


def lab_fields(
    outcome: LoggedOutcome,
    *,
    hint: bool | None = None,
    jobs: Iterable[str] = (),
    rid: str | None = None,
    emit_state: str | None = None,
    grant_remaining_ms: int | None = None,
    marker: str | None = None,
) -> dict[str, str]:
    """The full per-call lab record of design §2.7, validated field by field.

    ``jobs`` are handles (``j_<job_id>``), never canonical keys with
    incarnations; ``rid`` is the 32-hex reservation id.
    """
    fields = route_fields(outcome)
    if hint is not None:
        if type(hint) is not bool:
            raise LabLogError("ja_hint")
        fields["ja_hint"] = "1" if hint else "0"
    handles = tuple(jobs)
    if handles:
        if len(handles) > 8 or not all(
            type(h) is str and _HANDLE.fullmatch(h) for h in handles
        ):
            raise LabLogError("ja_job")
        fields["ja_job"] = ",".join(handles)
    if rid is not None:
        if type(rid) is not str or _RID.fullmatch(rid) is None:
            raise LabLogError("rid")
        fields["rid"] = rid
    if emit_state is not None:
        if type(emit_state) is not str or emit_state not in _EMIT_STATES:
            raise LabLogError("emit_state")
        fields["emit_state"] = emit_state
    if grant_remaining_ms is not None:
        if type(grant_remaining_ms) is not int or grant_remaining_ms < 0:
            raise LabLogError("grant_remaining_ms")
        fields["grant_remaining_ms"] = str(grant_remaining_ms)
    if marker is not None:
        if type(marker) is not str or marker not in LAB_MARKERS:
            raise LabLogError("ja_lab_marker")
        fields["ja_lab_marker"] = marker
    return {name: _checked(name, value) for name, value in fields.items()}


def format_fields(fields: Mapping[str, str]) -> str:
    """One ``key=value`` line in insertion order; values are pre-validated."""
    return " ".join(f"{name}={_checked(name, value)}" for name, value in fields.items())


def raw_value_hits(text: str, allowed: Iterable[str] = ()) -> list[str]:
    """Raw-value scan of an export (design §2.7, A2-04).

    Every match of ``RAW_VALUE`` is a hit unless it is exactly one of the
    registered synthetic test values in ``allowed``. A match that only
    contains or is contained in an allowed value is still a hit.
    """
    exact = frozenset(allowed)
    return [m.group(0) for m in RAW_VALUE.finditer(text) if m.group(0) not in exact]
