"""Default-disabled synthetic carrier; no production registration or identity inference."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from threading import Event
from typing import Any, Protocol, TypeVar

from fastmcp.tools.base import Tool, ToolResult
from mcp.types import ContentBlock, TextContent

from binnacle.mcp.job_awareness_hint_identity import (
    NATIVE_TOOL_TYPES,
    Execution,
    Identity,
    canonical_schema,
    claim,
    native_tool,
    producer_identity,
    witnessed_call,
    witnessed_tool,
)
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
    "NATIVE_TOOL_TYPES",
    "Execution",
    "HintAdapter",
    "HintBindings",
    "Identity",
    "Meter",
    "Schema",
    "Unsupported",
    "Workers",
    "canonical_schema",
    "equal",
    "native_tool",
    "producer_identity",
    "walk",
    "witnessed_call",
    "witnessed_tool",
]

META_KEY = "binnacle/job-awareness/synthetic-v1"
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
    schema: Any = field(init=False)
    identity: Identity | None = field(init=False)
    bound_tool: Tool = field(init=False, repr=False, compare=False)
    # Snapshot of the serverInfo stamp that the dispatching server adds to every
    # result. Bind it with ``bind_server``; never hand-write it (OBS-01).
    server_info: Any = None
    enabled: bool = False
    carrier: Enum | None = None
    exclusive: bool = False
    last_meter: Meter | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if type(self.bindings) is not HintBindings:
            raise ValueError("explicit hint bindings required")
        if (
            not native_tool(self.tool)  # exact type first: no subclass hook runs
            or type(self.tool.name) is not str
            or not 1 <= len(self.tool.name) <= 128
            or (self.tool.version is not None and type(self.tool.version) is not str)
        ):
            raise ValueError("explicit native tool binding required")
        self.bound_tool = self.tool  # provenance snapshot of the registration
        self.carrier = self.bindings.meta if self.carrier is None else self.carrier
        try:
            self.schema = Schema(self.tool.output_schema)
        except (ValueError, TypeError, RecursionError):
            self.schema = None
        self.identity = None if self.schema is None else producer_identity(self.tool)

    def bind_server(self, server: object) -> None:
        """Bind the serverInfo stamp from the server that dispatches the tool.

        OBS-01: the byte reserve in ``_adapt`` trusts this stamp. A stale or
        smaller stamp lets a result that is too large on the wire receive a
        hint. A production composition must call this with the same server that
        registers the bound tool, after the server name and version are final.
        A server without a dict stamp binds None, which suppresses every hint.
        """
        stamp = getattr(getattr(server, "_mcp_server", None), "server_info_stamp", None)
        self.server_info = stamp if type(stamp) is dict else None

    async def adapt(
        self,
        original: ToolResult,
        *,
        execution: object = None,
    ) -> ToolResult:
        """Suppress unknown producers before worker admission or awareness reads.

        Provenance rule (CHATGPT-POST-01/02, ADV-G4-01): there is no ``tool``
        or name parameter, so a controller cannot pass a looked-up Tool. The
        producer comes only from ``execution``: the receipt that
        ``witnessed_call`` issued for the dispatch that returned exactly this
        ``original`` object after one ``witnessed_tool`` body completed. Any
        other value (a Tool object, a name, a registry result, a hand-built,
        reused or other-result receipt, None) suppresses and consumes
        nothing. The receipt guards against accidental controller mis-wiring;
        in-process code is trusted (see job_awareness_hint_identity). The
        receipt's Tool must BE the bound registered tool
        object (``is``) with a type that is exactly one of
        ``NATIVE_TOOL_TYPES`` (no subclasses). Its exact name,
        exact version and canonical-JSON output schema must also still equal
        the bound identity, and the structured result must validate against
        that schema. A value-equal but different object, any injected,
        mounted, proxied or transformed wrapper, any subclass, and a missing,
        None, non-Tool or malformed producer are unknown: the original result
        returns unchanged with no worker admission, observation read or
        receipt query. Caller-supplied name or version strings and request
        selectors are never an identity. No schema or identity is inferred
        from a result. The (name, version, schema) triple is only a contract
        identity (ADV-G4-02); the receipt's object identity is what tells two
        equal tools apart. Precondition: no
        middleware or interceptor inside ``witnessed_call`` rewrites the
        result object after the witnessed body completed.
        """
        if (
            self.enabled is not True
            or self.exclusive is not True
            or type(original) is not ToolResult
            or self.schema is None
            or self.identity is None
        ):
            return original
        tool = claim(execution, original)
        if tool is not self.bound_tool or not native_tool(tool):
            return original
        producer = producer_identity(tool, self.identity)
        if producer is None or producer != self.identity:
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
