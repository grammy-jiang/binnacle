"""Production Job Awareness: per-conversation STRUCT hints (default off).

When ``[job_awareness] hints_enabled = true``, the composition adds one
``JobAwarenessHints`` middleware. When the flag is off this module is never
imported, so ``tools/list`` and every tool result keep their bytes.

Flow for one ``tools/call`` (E2 design §2, production subset):

1. Gate. The client name must be exactly one of the configured ChatGPT names,
   and the reviewed route (``route_call`` + core ``session_route.route``) must
   return a keyed ``UNBOUND`` outcome: ``X-OpenAI-Session`` /
   ``X-OpenAI-Subject`` present once each, well formed, and equal to
   ``_meta["openai/session"]`` / ``_meta["openai/subject"]`` of the same
   call. Anything else gets the original result. The key is an HMAC digest
   under a per-process epoch key; no raw value is kept or logged.
2. Under the reviewed per-key fence: a ``run_command`` result with
   ``state == "running"`` binds its ``job_id`` to this key; a ``job_status``
   result that shows the job ``exited``, or a ``stop_job`` call, acknowledges
   the key's own job (no hint needed).
3. Pending jobs of this key are read through the injected job-state reader.
   For at most two ``exited`` jobs, a fixed-vocabulary hint is rendered and
   inserted into ``structuredContent`` as ``job_awareness_hint`` with the
   reviewed STRUCT rules (``insert_hint``: mirror rule, re-validation against
   the advertised schema; walk byte caps). Only after the insert succeeds are
   the jobs marked ``EMITTED``; every doubt returns the original result
   object and leaves the jobs ``PENDING`` (fail closed).

``tools/list`` for an allowed client declares the optional field
``job_awareness_hint: {"type": "string", "maxLength": 512}`` in each object
output schema that the reviewed ``Schema`` subset supports. Other clients get
the unchanged list.

Every bind, acknowledgement, emitted or suppressed hint and route refusal of
an allowed client writes one ``event=ja_*`` journal line. Lines carry the
call id, the tool, the 16-hex ``ja_key`` digest prefix and job ids only.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import re
import time
from collections.abc import Callable, Mapping
from enum import Enum
from typing import Any, Protocol

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp.types import ContentBlock, TextContent

from binnacle.mcp.callctx import current_call
from binnacle.mcp.identity import ClientIdentity
from binnacle.mcp.job_awareness_hint_schema import Schema
from binnacle.mcp.job_awareness_hint_struct import (
    HINT_FIELD,
    HINT_FIELD_SCHEMA,
    declares_hint_field,
    insert_hint,
)
from binnacle.mcp.job_awareness_hint_walk import Meter, Unsupported, _string, walk
from binnacle.mcp.job_awareness_live_ledger import Ledger, valid_job_id
from binnacle.mcp.job_awareness_route import RAW_VALUE, Classifier, route_call

__all__ = [
    "HINT_PREFIX",
    "MAX_HINT_JOBS",
    "JobAwarenessHints",
    "advertised_schema",
    "declares_open_hint_field",
    "insert_struct_hint",
    "render_hint",
]

logger = logging.getLogger("binnacle.job_awareness")

HINT_PREFIX = "[Binnacle job reminder]"
MAX_HINT_JOBS = 2
#: The wire byte budget and growth cap of the reviewed carrier
#: (``job_awareness_hint.HintAdapter._render``).
_WIRE_LIMIT = 262144
_GROWTH_LIMIT = 1024
_STAMP_KEY = "io.modelcontextprotocol/serverInfo"
_FIELD_VALUE = re.compile(r"[A-Za-z0-9_.:,-]{1,128}")
_TOOL_NAME = re.compile(r"[a-z_]{1,64}")
_LOG_KEY = re.compile(r"[0-9a-f]{16}")
_KD = re.compile(r"[0-9a-f]{32}:[0-9a-f]{32}:[0-9a-f]{32}")


class Fences(Protocol):
    """The reviewed core ``session_fence.FenceSet`` (injected)."""

    def hold(self, kd: str) -> Any: ...


# --------------------------------------------------------------------- schema


def advertised_schema(schema: object) -> dict[str, Any] | None:
    """The output schema with the optional hint field declared, or None.

    Only an open object schema (no ``additionalProperties``) with a
    ``properties`` map that lacks the field, and that the reviewed ``Schema``
    subset compiles, is extended. The field is appended last and never
    required. None means: list the tool unchanged, never hint it.
    """
    if (
        type(schema) is not dict
        or schema.get("type") != "object"
        or type(schema.get("properties")) is not dict
        or HINT_FIELD in schema["properties"]
        or "additionalProperties" in schema
    ):
        return None
    extended = copy.deepcopy(schema)
    extended["properties"][HINT_FIELD] = dict(HINT_FIELD_SCHEMA)
    try:
        compiled = Schema(extended)
    except (ValueError, TypeError, RecursionError):
        return None
    return extended if declares_open_hint_field(compiled.value) else None


def declares_open_hint_field(schema: object) -> bool:
    """The reviewed STRUCT bind rule, for an open production schema.

    ``declares_hint_field`` requires a closed schema. Production output
    schemas are open (no ``additionalProperties``). The field rule itself is
    unchanged: exactly ``{"type": "string", "maxLength": 512}``, optional.
    """
    if type(schema) is not dict or "additionalProperties" in schema:
        return False
    return declares_hint_field({**schema, "additionalProperties": False})


# --------------------------------------------------------------------- render


def _exit_words(state: Mapping[str, Any]) -> str:
    signal, code = state.get("signal"), state.get("exit_code")
    if type(signal) is int and 0 < signal < 256:
        return f"signal {signal}"
    if type(code) is int and -256 < code < 256:
        return f"exit_code {code}"
    return "exit status unknown"


def render_hint(finished: tuple[tuple[str, Mapping[str, Any]], ...]) -> str | None:
    """Fixed-vocabulary text: job ids and exit words only; at most 512 bytes."""
    if type(finished) is not tuple or not 1 <= len(finished) <= MAX_HINT_JOBS:
        return None
    if not all(valid_job_id(job) for job, _ in finished):
        return None
    if len({job for job, _ in finished}) != len(finished):
        return None
    if len(finished) == 1:
        job, state = finished[0]
        text = (
            f"{HINT_PREFIX} Background job {job}, started earlier in this "
            f"conversation, has finished ({_exit_words(state)}). Its final "
            f"output has not been read here; call job_status with job_id "
            f"{job} to read it."
        )
    else:
        parts = "; ".join(f"{job} ({_exit_words(state)})" for job, state in finished)
        text = (
            f"{HINT_PREFIX} Background jobs started earlier in this conversation "
            f"have finished: {parts}. Their final output has not been read "
            f"here; call job_status with each job_id to read it."
        )
    return text if len(text.encode("utf-8")) <= 512 else None


# -------------------------------------------------------------------- carrier


def insert_struct_hint(
    original: object, text: str, schema: object, stamp: object
) -> ToolResult | str:
    """A new result with the hint field, or the suppression reason.

    The steps and limits are those of the reviewed routed render
    (``HintAdapter._render``, STRUCT branch): a bounded walk with the
    serverInfo stamp reserved, validation of the original structured content,
    ``insert_hint`` (mirror rule and re-validation), a second bounded walk
    and the 1024-byte growth cap. The original object is never changed.
    """
    if type(original) is not ToolResult:
        return "result_type"
    if original.is_error is not False:
        return "error_result"
    if type(original.structured_content) is not dict:
        return "no_structure"
    if type(stamp) is not dict:
        return "stamp"
    try:
        compiled = Schema(schema)
    except (ValueError, TypeError, RecursionError):
        return "schema"
    if not declares_open_hint_field(compiled.value):
        return "schema"
    meter = Meter()
    try:
        walk({"_meta": {_STAMP_KEY: stamp}}, meter)
        overhead = meter.bytes
        walk(original, meter, byte_limit=_WIRE_LIMIT - overhead)
        original_bytes = meter.bytes - (13 if original.meta is None else 0)
        meter.initial = False
        body = walk(original, meter, copy=True, byte_limit=_WIRE_LIMIT - overhead)
        if not compiled.valid(body["structuredContent"], meter):
            return "invalid_original"
        _string(text, meter, _WIRE_LIMIT + 1024, raw_limit=512)
        if not insert_hint(body, text, compiled, meter):
            return "insert"
        walk(body, meter, byte_limit=_WIRE_LIMIT + 1024 - overhead)
        if meter.bytes - original_bytes > _GROWTH_LIMIT:
            return "growth"
    except Unsupported:
        return "unsupported"
    blocks: list[ContentBlock] = [
        TextContent.model_construct(**block) for block in body["content"]
    ]
    return ToolResult.model_construct(
        content=blocks,
        structured_content=body["structuredContent"],
        meta=body["_meta"],
    )


# ---------------------------------------------------------------------- logs


def _line(event: str, **fields: str) -> str | None:
    """``event=... key=value`` with every value validated; None refuses."""
    parts = [f"event={event}"]
    for name, value in fields.items():
        if (
            type(value) is not str
            or _FIELD_VALUE.fullmatch(value) is None
            or RAW_VALUE.search(value) is not None
        ):
            return None
        parts.append(f"{name}={value}")
    return " ".join(parts)


def _log(event: str, **fields: str) -> None:
    line = _line(event, **fields)
    logger.info("%s", line if line is not None else f"event={event} fields=refused")


def _keyed(outcome: object) -> tuple[str, str] | str:
    """``(kd, log_key)`` for a keyed ``UNBOUND`` outcome, else its status."""
    try:
        status, key = outcome.status, outcome.key  # type: ignore[attr-defined]
        value = status.value if isinstance(status, Enum) else None
        if value != "UNBOUND" or key is None:
            return value if type(value) is str else "UNKNOWN"
        kd, log_key = key.kd, key.log_key
    except AttributeError:
        return "UNKNOWN"
    if (
        type(kd) is not str
        or _KD.fullmatch(kd) is None
        or type(log_key) is not str
        or _LOG_KEY.fullmatch(log_key) is None
    ):
        return "UNKNOWN"
    return kd, log_key


# ----------------------------------------------------------------- middleware


class JobAwarenessHints(Middleware):
    """The production carrier; innermost root middleware."""

    def __init__(
        self,
        *,
        classify: Classifier[object],
        fences: Fences,
        identity: ClientIdentity,
        client_names: tuple[str, ...],
        job_state: Callable[[str], Mapping[str, Any] | None],
        server: object,
        ledger: Ledger | None = None,
        clock: Callable[[], float] = time.monotonic,
        state_timeout_s: float = 2.0,
    ) -> None:
        self._classify = classify
        self._fences = fences
        self._identity = identity
        self._clients = frozenset(client_names)
        self._job_state = job_state
        self._server = server
        self.ledger = Ledger() if ledger is None else ledger
        self._clock = clock
        self._timeout = state_timeout_s

    def _allowed(self, context: MiddlewareContext) -> bool:
        name = self._identity.resolve(context)
        return type(name) is str and name in self._clients

    async def on_list_tools(self, context: MiddlewareContext, call_next: CallNext):
        tools = await call_next(context)
        try:
            if not self._allowed(context):
                return tools
            listed = []
            for tool in tools:
                schema = advertised_schema(tool.output_schema)
                listed.append(
                    tool
                    if schema is None
                    else tool.model_copy(update={"output_schema": schema})
                )
            return listed
        except Exception:  # noqa: BLE001 - an awareness failure keeps the list
            _log("ja_list", outcome="unchanged", reason="internal")
            return tools

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext):
        gate = self._gate(context)
        result = await call_next(context)
        if gate is None:
            return result
        try:
            return await self._after(context, gate, result)
        except Exception:  # noqa: BLE001 - every failure keeps the original
            _log(
                "ja_hint",
                outcome="suppressed",
                reason="internal",
                call=current_call.get(),
                ja_key=gate[1],
            )
            return result

    def _gate(self, context: MiddlewareContext) -> tuple[str, str] | None:
        """The route key of an allowed client's well-formed call, else None."""
        try:
            if not self._allowed(context):
                return None
            keyed = _keyed(route_call(self._classify))
        except Exception:  # noqa: BLE001 - fail closed
            keyed = "UNKNOWN"
        if isinstance(keyed, str):
            _log(
                "ja_route",
                status=keyed,
                call=current_call.get(),
                tool=_tool_name(context),
            )
            return None
        return keyed

    async def _states(
        self, jobs: tuple[str, ...]
    ) -> dict[str, Mapping[str, Any] | None | str]:
        """Job id -> state mapping, None (job gone) or ``"error"``."""
        states: dict[str, Mapping[str, Any] | None | str] = {}
        for job in jobs:
            try:
                state = await asyncio.wait_for(
                    asyncio.to_thread(self._job_state, job), self._timeout
                )
            except Exception:  # noqa: BLE001 - unreadable: never hinted now
                states[job] = "error"
                continue
            states[job] = (
                state if state is None or isinstance(state, Mapping) else "error"
            )
        return states

    async def _after(
        self, context: MiddlewareContext, gate: tuple[str, str], result: object
    ) -> object:
        kd, log_key = gate
        tool = _tool_name(context)
        call = current_call.get()
        base = {"call": call, "tool": tool, "ja_key": log_key}
        if tool != "run_command" and not self.ledger.pending(kd, self._clock()):
            # Nothing to bind, acknowledge or hint. Skipping the fence also
            # keeps FenceSet (no eviction) to conversations that start jobs.
            return result
        async with self._fences.hold(kd) as held:
            now = self._clock()
            if not held:
                if self.ledger.pending(kd, now):
                    _log("ja_hint", outcome="suppressed", reason="busy", **base)
                return result
            fresh = self._record(context, tool, result, kd, now, base)
            pending = tuple(j for j in self.ledger.pending(kd, now) if j != fresh)
            if not pending:
                return result
            states = await self._states(pending)
            now = self._clock()
            finished: list[tuple[str, Mapping[str, Any]]] = []
            for job in pending:
                state = states.get(job)
                if state is None:
                    self.ledger.forget(kd, job, now)
                elif isinstance(state, Mapping) and state.get("state") == "exited":
                    finished.append((job, state))
            if not finished:
                return result
            chosen = tuple(finished[:MAX_HINT_JOBS])
            ids = ",".join(job for job, _ in chosen)
            text = render_hint(chosen)
            outcome: ToolResult | str = "render" if text is None else "schema"
            if text is not None:
                found = await self._server.get_tool(context.message.name)  # type: ignore[attr-defined]
                schema = (
                    None if found is None else advertised_schema(found.output_schema)
                )
                if schema is not None:
                    stamp = getattr(
                        getattr(self._server, "_mcp_server", None),
                        "server_info_stamp",
                        None,
                    )
                    outcome = insert_struct_hint(result, text, schema, stamp)
            if isinstance(outcome, str):
                _log("ja_hint", outcome="suppressed", reason=outcome, jobs=ids, **base)
                return result
            if not self.ledger.emitted(kd, tuple(job for job, _ in chosen), now):
                _log("ja_hint", outcome="suppressed", reason="state", jobs=ids, **base)
                return result
            _log("ja_hint", outcome="emitted", jobs=ids, **base)
            return outcome

    def _record(
        self,
        context: MiddlewareContext,
        tool: str,
        result: object,
        kd: str,
        now: float,
        base: dict[str, str],
    ) -> str | None:
        """Bind or acknowledge from this call; returns a job bound just now."""
        if type(result) is not ToolResult or result.is_error is not False:
            return None
        structured = result.structured_content
        if type(structured) is not dict:
            return None
        job = structured.get("job_id")
        if type(job) is not str or not valid_job_id(job):
            return None
        if tool == "run_command" and structured.get("state") == "running":
            outcome = self.ledger.bind(kd, job, now)
            if outcome == "bound":
                _log("ja_bind", outcome="bound", job=job, **base)
                return job
            _log("ja_bind", outcome="refused", reason=outcome, job=job, **base)
            return None
        arguments = getattr(context.message, "arguments", None) or {}
        if arguments.get("job_id") != job:
            return None
        seen = tool == "stop_job" or (
            tool == "job_status" and structured.get("state") == "exited"
        )
        if seen and self.ledger.ack(kd, job, now):
            _log("ja_ack", job=job, **base)
        return None


def _tool_name(context: MiddlewareContext) -> str:
    name = getattr(context.message, "name", None)
    return name if type(name) is str and _TOOL_NAME.fullmatch(name) else "-"
