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

ADV-G4-01: the producer is never looked up. A controller cannot name a Tool
(by object, name or registry lookup); it can only hand over an ``Execution``
receipt. ``ExecutionScope`` issues one only when exactly one body made by
``witnessed_tool`` ran inside the scope, on the scope's own server, outside
any tool transform. The receipt is single-use and cannot be constructed or
subclassed outside this module.
"""

from __future__ import annotations

import functools
import inspect
import json
import threading
from collections.abc import Callable
from contextvars import ContextVar
from types import TracebackType
from typing import Any, final

from fastmcp.server.dependencies import get_server
from fastmcp.tools import tool_transform
from fastmcp.tools.base import Tool
from fastmcp.tools.function_tool import FunctionTool

from binnacle.mcp.job_awareness_hint_walk import Meter, walk

__all__ = [
    "NATIVE_TOOL_TYPES",
    "Execution",
    "ExecutionScope",
    "Identity",
    "canonical_schema",
    "claim",
    "native_tool",
    "producer_identity",
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


_MINT = object()
_LOCK = threading.Lock()
_SCOPE: ContextVar[ExecutionScope | None] = ContextVar(
    "binnacle_job_awareness_execution_scope", default=None
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


class _Seal:
    __slots__ = ("tool",)

    def __init__(self) -> None:
        self.tool: FunctionTool | None = None

    def record(self) -> None:
        scope = _SCOPE.get()
        if scope is not None:
            scope._record(self, _transformed() or _server() is not scope._server)


@final
class Execution:
    """Single-use receipt for the sealed Tool whose body actually ran."""

    __slots__ = ("_spent", "_tool")

    def __init__(self, mint: object, tool: object) -> None:
        if mint is not _MINT:
            raise TypeError("execution receipts are issued only by ExecutionScope")
        object.__setattr__(self, "_tool", tool)
        object.__setattr__(self, "_spent", False)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("Execution cannot be subclassed")

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Execution is immutable")


def claim(execution: object) -> object | None:
    """Return the receipt's Tool once; any other value or a reused receipt is None."""
    if type(execution) is not Execution:
        return None
    with _LOCK:
        if object.__getattribute__(execution, "_spent") is not False:
            return None
        object.__setattr__(execution, "_spent", True)
    return object.__getattribute__(execution, "_tool")


@final
class ExecutionScope:
    """Wrap exactly one dispatch (``call_next``) in the controller, then call
    ``execution()``. Nothing ran, two runs, a run on another (mounted) server,
    a run under a tool transform, a late run, an open scope or a second
    ``execution()`` call all give None (unknown producer: suppress).
    """

    def __init__(self) -> None:
        self._records: list[tuple[_Seal, bool]] = []
        self._server: object | None = None
        self._token: Any = None
        self._state = "new"

    def __enter__(self) -> ExecutionScope:
        if self._state != "new":
            raise RuntimeError("an execution scope is single-use")
        self._server = _server()
        self._token = _SCOPE.set(self)
        self._state = "open"
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _SCOPE.reset(self._token)
        with _LOCK:
            self._state = "closed"

    def _record(self, seal: _Seal, poisoned: bool) -> None:
        with _LOCK:
            self._records.append((seal, poisoned or self._state != "open"))

    def execution(self) -> Execution | None:
        with _LOCK:
            if self._state != "closed":
                return None
            self._state = "issued"
            records = tuple(self._records)
        if self._server is None or len(records) != 1:
            return None
        seal, poisoned = records[0]
        if poisoned or seal.tool is None or not native_tool(seal.tool):
            return None
        return Execution(_MINT, seal.tool)


def witnessed_tool(fn: Callable[..., Any], /, **options: Any) -> FunctionTool:
    """Build a FunctionTool whose body records its own run in the current scope.

    Only this Tool object can appear in a receipt for this body; copies,
    wrappers and other registrations of the same handler cannot.
    """
    if not inspect.isfunction(fn) and not inspect.ismethod(fn):
        raise ValueError("witnessed tools need a plain function")
    if inspect.isgeneratorfunction(fn) or inspect.isasyncgenfunction(fn):
        raise ValueError("witnessed tools need a plain function")
    seal = _Seal()

    @functools.wraps(fn)
    async def run_async(*args: Any, **kwargs: Any) -> Any:
        seal.record()
        return await fn(*args, **kwargs)

    @functools.wraps(fn)
    def run_sync(*args: Any, **kwargs: Any) -> Any:
        seal.record()
        return fn(*args, **kwargs)

    body = run_async if inspect.iscoroutinefunction(fn) else run_sync
    tool = FunctionTool.from_function(body, **options)
    if type(tool) is not FunctionTool:
        raise ValueError("witnessed tools must be exact FunctionTool objects")
    seal.tool = tool
    return tool
