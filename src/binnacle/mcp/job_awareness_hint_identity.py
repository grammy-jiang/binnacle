"""Producer provenance: the bound native Tool object, never caller strings.

FastMCP 4.1.0 does not make (name, version) or even (name, version, schema)
unique: ToolInjectionMiddleware overrides by name, a parent local tool shadows
an unnamespaced mounted child, transforms rename or redeclare tools, and a
Tool subclass can report an effective output schema that differs from its
backing field map (CHATGPT-POST-01/02). Provenance is therefore object
identity with the bound registered tool plus an exact reviewed native type
(no subclasses, no mounted, proxied, OpenAPI or transformed wrappers). The
(name, version, canonical-JSON output schema) identity remains an additional
condition. It is read from the backing field map of an exact-typed object, so
no descriptor, comparison or hashing callback of any field value runs.

ADV-G4-01: the producer is never looked up by name, version or registry.
The controller hands over an ``Execution`` receipt from ``witnessed_call``.
It is issued only when exactly one ``witnessed_tool`` body completed during
that dispatch, on the dispatching server, outside any tool transform, and it
names the exact ToolResult object the dispatch returned. The adapter accepts
it once, and only for that result object.

Threat model: all Python code in this interpreter (middleware, composition,
controllers, tests) is trusted. The receipt protects against accidental
mis-wiring by a controller: the wrong tool, the wrong result, a result of
another call, a failed or cancelled body, or a reused receipt. It is not a
security boundary against hostile in-process code. Such code can reach any
object through introspection (``object.__new__``, ``object.__setattr__``,
``__globals__``, closure cells) and can forge a receipt or a witness record.
"""

from __future__ import annotations

import functools
import inspect
import json
import threading
import weakref
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from fastmcp.server.dependencies import get_server
from fastmcp.tools import tool_transform
from fastmcp.tools.base import Tool, ToolResult
from fastmcp.tools.function_tool import FunctionTool

from binnacle.mcp.job_awareness_hint_walk import Meter, walk

__all__ = [
    "NATIVE_TOOL_TYPES",
    "Execution",
    "Identity",
    "canonical_schema",
    "claim",
    "native_tool",
    "producer_identity",
    "witnessed_call",
    "witnessed_tool",
]

Identity = tuple[str, str | None, str]
_FIELDS = ("name", "version", "output_schema")
# Reviewed directly registered FastMCP 4.1.0 classes. Wrappers (TransformedTool,
# FastMCPProviderTool, ProxyTool, OpenAPITool) and every subclass are excluded.
NATIVE_TOOL_TYPES: tuple[type[Tool], ...] = (Tool, FunctionTool)


def native_tool(tool: object) -> bool:
    """True only for an exact reviewed native type; ``type()`` runs no hook."""
    cls = type(tool)
    return any(cls is native for native in NATIVE_TOOL_TYPES)


def canonical_schema(schema: Any) -> str:
    """Bounded exact canonical JSON; raises for unsupported or oversized values."""
    meter = Meter()
    walk(schema, meter, node_limit=256)
    meter.initial = False
    value = walk(schema, meter, copy=True, node_limit=256)
    if type(value) is not dict:
        raise ValueError("output schema must be an object")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def producer_identity(tool: object) -> Identity | None:
    """Return (name, version, canonical schema) of a native Tool, else None.

    None means unknown: the caller must suppress. The exact-type check runs
    before any attribute, key lookup or equality, so a subclass (hostile or
    not) is unknown and never gets a callback.
    """
    try:
        if not native_tool(tool):
            return None
        data = object.__getattribute__(tool, "__dict__")
        if (
            type(data) is not dict
            or len(data) > 64
            or not all(type(key) is str for key in data)
            or not all(name in data for name in _FIELDS)
        ):
            return None
        name, version, schema = (data[field] for field in _FIELDS)
        if (
            type(name) is not str
            or not 1 <= len(name) <= 128
            or (version is not None and type(version) is not str)
            or (version is not None and len(version) > 128)
            or type(schema) is not dict
        ):
            return None
        return name, version, canonical_schema(schema)
    except Exception:  # noqa: BLE001 - unknown producer identity suppresses
        return None


C = TypeVar("C")
R = TypeVar("R")
_LOCK = threading.Lock()


@dataclass(frozen=True, eq=False)
class Execution:
    """Receipt for one witnessed dispatch: the Tool whose body completed and
    the exact result object that the dispatch returned. Only receipts that
    ``witnessed_call`` issued and nobody consumed yet are accepted.
    """

    tool: FunctionTool
    result: object


_ISSUED: weakref.WeakSet[Execution] = weakref.WeakSet()


class _Dispatch:
    """The bodies that completed during one ``witnessed_call``."""

    __slots__ = ("records", "server")

    def __init__(self, server: object | None) -> None:
        self.server = server
        self.records: list[tuple[FunctionTool | None, bool]] = []


_DISPATCH: ContextVar[_Dispatch | None] = ContextVar(
    "binnacle_job_awareness_dispatch", default=None
)


def _server() -> object | None:
    try:
        return get_server()
    except Exception:  # noqa: BLE001 - no dispatching server: unknown
        return None


def _transformed() -> bool:
    """True inside a TransformedTool forward; unknown FastMCP internals fail closed."""
    current = getattr(tool_transform, "_current_tool", None)
    return type(current) is not ContextVar or current.get() is not None


def _completed(tool: FunctionTool | None) -> None:
    """Record that a witnessed body returned; a foreign record poisons.

    A record that arrives after its dispatch returned is never read.
    """
    dispatch = _DISPATCH.get()
    if dispatch is None:
        return
    foreign = _transformed() or _server() is not dispatch.server
    with _LOCK:
        dispatch.records.append((tool, foreign))


async def witnessed_call(
    call_next: Callable[[C], Awaitable[R]], context: C
) -> tuple[R, Execution | None]:
    """Run one dispatch and return its result with a receipt or None.

    No receipt is issued when the dispatch raised or was cancelled (the
    exception propagates), when no body or more than one body completed, when
    a body completed on another (mounted) server or under a tool transform,
    when there is no dispatching server, or when the result is not an exact
    ToolResult. With a receipt, the caller gets a per-call shallow copy of
    the result: a body or a caching middleware may return one ToolResult
    object for several calls, and the receipt binds this call's object only.
    """
    dispatch = _Dispatch(_server())
    token = _DISPATCH.set(dispatch)
    try:
        result = await call_next(context)
    finally:
        _DISPATCH.reset(token)
        with _LOCK:
            records = tuple(dispatch.records)
    if type(result) is not ToolResult or dispatch.server is None:
        return result, None
    if len(records) != 1:
        return result, None
    tool, poisoned = records[0]
    if poisoned or tool is None or not native_tool(tool):
        return result, None
    fresh = cast(R, cast(ToolResult, result).model_copy())
    execution = Execution(tool, fresh)
    with _LOCK:
        _ISSUED.add(execution)
    return fresh, execution


def claim(execution: object, result: object) -> object | None:
    """Validate, then consume: the receipt's Tool once, for its own result only.

    Anything that is not an issued, unconsumed receipt for exactly ``result``
    gives None and consumes nothing.
    """
    if type(execution) is not Execution:
        return None
    with _LOCK:
        if execution not in _ISSUED or execution.result is not result:
            return None
        _ISSUED.discard(execution)
    return execution.tool


def witnessed_tool(fn: Callable[..., Any], /, **options: Any) -> FunctionTool:
    """Build a FunctionTool whose body records its own successful return.

    A body that raises or is cancelled records nothing. The record names this
    Tool object only; copies and wrappers of it are not the bound producer.
    """
    if not inspect.isfunction(fn) and not inspect.ismethod(fn):
        raise ValueError("witnessed tools need a plain function")
    if inspect.isgeneratorfunction(fn) or inspect.isasyncgenfunction(fn):
        raise ValueError("witnessed tools need a plain function")
    holder: list[FunctionTool | None] = [None]

    @functools.wraps(fn)
    async def run_async(*args: Any, **kwargs: Any) -> Any:
        value = await fn(*args, **kwargs)
        _completed(holder[0])
        return value

    @functools.wraps(fn)
    def run_sync(*args: Any, **kwargs: Any) -> Any:
        value = fn(*args, **kwargs)
        _completed(holder[0])
        return value

    body = run_async if inspect.iscoroutinefunction(fn) else run_sync
    tool = FunctionTool.from_function(body, **options)
    if type(tool) is not FunctionTool:
        raise ValueError("witnessed tools must be exact FunctionTool objects")
    holder[0] = tool
    return tool
