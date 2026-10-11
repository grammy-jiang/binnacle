"""Default-disabled synthetic carrier; no production registration or identity inference."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from threading import Event
from typing import Any, Protocol, TypeVar

from fastmcp.tools.base import Tool, ToolResult
from mcp.types import ContentBlock, TextContent

from binnacle.mcp.job_awareness_hint_schema import Schema, equal
from binnacle.mcp.job_awareness_hint_walk import (
    Meter,
    Unsupported,
    _fields,
    _string,
    walk,
)

__all__ = [
    "META_KEY",
    "HintAdapter",
    "HintBindings",
    "Meter",
    "Schema",
    "Unsupported",
    "Workers",
    "equal",
    "walk",
]

META_KEY = "binnacle/job-awareness/synthetic-v1"
_UNKNOWN_VERSION = object()
T = TypeVar("T")


class Workers(Protocol):
    """Synthetic app owns admission, worker lifetime, and drain on shutdown."""

    async def run(self, action: Callable[[Event], T], busy: T) -> T: ...


@dataclass(frozen=True)
class HintBindings:
    """Trusted local composition only; validation never establishes authority."""

    check: Callable[[Any, Any, frozenset[Any]], Enum]
    observe: Callable[[Any, Any], Any]
    select: Callable[[Any, tuple[Any, ...]], tuple[Any, ...]]
    render: Callable[[tuple[Any, ...], Any], Any]
    hint_type: type
    grant_type: type
    job_type: type
    success_type: type[Any]
    observe_scope: Enum
    authorized: Enum
    meta: Enum
    text: Enum

    def __post_init__(self) -> None:
        funcs = self.check, self.observe, self.select, self.render
        types = self.hint_type, self.grant_type, self.job_type, self.success_type
        enums = self.observe_scope, self.authorized, self.meta, self.text
        if (
            not all(callable(f) for f in funcs)
            or not all(isinstance(t, type) for t in types)
            or not all(isinstance(e, Enum) for e in enums)
            or type(self.meta) is not type(self.text)
            or self.meta is self.text
        ):
            raise ValueError("invalid hint bindings")


@dataclass
class HintAdapter:
    bindings: HintBindings
    grant: object
    jobs: tuple[object, ...]
    tool: Tool
    workers: Workers
    tool_name: str = field(init=False)
    tool_version: str | None = field(init=False)
    schema: Any = field(init=False)
    server_info: Any = None  # controller snapshot of the pinned native server stamp
    enabled: bool = False
    carrier: Enum | None = None
    exclusive: bool = False
    last_meter: Meter | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if type(self.bindings) is not HintBindings:
            raise ValueError("explicit hint bindings required")
        if (
            not isinstance(self.tool, Tool)
            or type(self.tool.name) is not str
            or not 1 <= len(self.tool.name) <= 128
            or (self.tool.version is not None and type(self.tool.version) is not str)
        ):
            raise ValueError("explicit native tool binding required")
        self.tool_name = self.tool.name
        self.tool_version = self.tool.version
        self.carrier = self.bindings.meta if self.carrier is None else self.carrier
        try:
            self.schema = Schema(self.tool.output_schema)
        except (ValueError, TypeError, RecursionError):
            self.schema = None

    async def adapt(
        self,
        original: ToolResult,
        *,
        tool_name: object = None,
        tool_version: object = _UNKNOWN_VERSION,
    ) -> ToolResult:
        """Suppress unknown producers before worker admission or awareness reads.

        The controller must supply the registered native tool at construction and
        the resolved producing tool's exact name AND version on every call.
        Explicit None means an unversioned producer; omission means unknown.
        A request selector is not a resolved version: default dispatch, version
        aliases and unversioned fallback must be resolved by native FastMCP.
        No schema or identity is inferred from a result. Registrations and
        routing stay fixed for this adapter's lifetime; rebuild on changes.
        """
        if (
            self.enabled is not True
            or self.exclusive is not True
            or type(original) is not ToolResult
            or self.schema is None
            or type(tool_name) is not str
            or len(tool_name) > 128
            or tool_name != self.tool_name
            or (tool_version is not None and type(tool_version) is not str)
            or tool_version != self.tool_version
        ):
            return original
        return await self.workers.run(
            lambda stop: self._adapt(original, stop), original
        )

    def _adapt(self, original: ToolResult, stop: Event) -> ToolResult:
        binding = self.bindings
        meter = Meter(stop)
        self.last_meter = meter
        try:
            if type(self.server_info) is not dict:
                return original
            stamp = {"io.modelcontextprotocol/serverInfo": self.server_info}
            walk({"_meta": stamp}, meter)
            overhead = meter.bytes  # Reserve the entire framework metadata wrapper.
            walk(original, meter, byte_limit=262144 - overhead)
            original_bytes = meter.bytes - (13 if original.meta is None else 0)
            meter.initial = False
            body = walk(original, meter, copy=True, byte_limit=262144 - overhead)
            if not self.schema.valid(body["structuredContent"], meter):
                return original
            if (
                type(self.jobs) is not tuple
                or not 1 <= len(self.jobs) <= 8
                or not isinstance(self.grant, binding.grant_type)
                or not all(type(job) is binding.job_type for job in self.jobs)
                or not any(self.carrier is c for c in (binding.meta, binding.text))
            ):
                return original
            observations = []
            scope = frozenset({binding.observe_scope})
            for job in self.jobs:
                meter.charge()
                if binding.check(self.grant, job, scope) is not binding.authorized:
                    return original
                observed = binding.observe(self.grant, job)
                if type(observed) is not binding.success_type:
                    return original
                record = observed.value
                if record.job != job:
                    return original
                observations.append(record)
            candidates = binding.select(self.grant, tuple(observations))
            hint = binding.render(candidates, self.carrier)
            if type(hint) is not binding.hint_type:
                return original
            data = object.__getattribute__(hint, "__dict__")
            if (
                not _fields(data, ("carrier", "text", "utf8_bytes"))
                or data["carrier"] is not self.carrier
                or type(data["text"]) is not str
                or type(data["utf8_bytes"]) is not int
                or not 1 <= data["utf8_bytes"] <= 512
            ):
                return original
            text = data["text"]
            _string(text, meter, 263168, raw_limit=512)
            if len(text.encode("utf-8")) != data["utf8_bytes"]:
                return original
            meter.charge(4096)  # fixed renderer and bounded carrier construction
            if self.carrier is binding.meta:
                meta = body["_meta"]
                if meta is None:
                    meta = body["_meta"] = {}
                if META_KEY in meta:
                    return original
                meta[META_KEY] = text
            else:
                new = {"type": "text", "text": text, "annotations": None, "_meta": None}
                body["content"].append(new)
            walk(body, meter, byte_limit=263168 - overhead)
            if meter.bytes - original_bytes > 1024:
                return original
            meter.charge(meter.bytes + meter.nodes + 32 * len(body["content"]))
            blocks: list[ContentBlock] = []
            blocks.extend(TextContent.model_construct(**c) for c in body["content"])
            return ToolResult.model_construct(
                content=blocks,
                structured_content=body["structuredContent"],
                meta=body["_meta"],
            )
        except Exception:  # noqa: BLE001 - all awareness failures preserve the original
            return original
