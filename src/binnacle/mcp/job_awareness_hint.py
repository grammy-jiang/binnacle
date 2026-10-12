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
    NO_STRUCTURE,
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
    "MAX_RENDERED",
    "META_KEY",
    "NATIVE_TOOL_TYPES",
    "NO_STRUCTURE",
    "Execution",
    "HintAdapter",
    "HintBindings",
    "Identity",
    "Meter",
    "RoutedOutcome",
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
#: Mirrors hint_policy/hint_render MAX_HINT_JOBS; the adapter may not import them.
MAX_RENDERED = 2
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
    # CA-2, read only by ``adapt_routed``; None makes every routed call
    # suppress. ``route_type`` is the core's frozen request-local SessionRoute
    # and ``candidate_type`` the exact type of the values ``select`` returns.
    route_type: type | None = None
    candidate_type: type | None = None

    def __post_init__(self) -> None:
        funcs = self.check, self.observe, self.select, self.render
        types = self.hint_type, self.grant_type, self.job_type, self.success_type
        enums = self.observe_scope, self.authorized, self.meta, self.text
        if (
            not all(callable(f) for f in funcs)
            or not all(isinstance(t, type) for t in types)
            or not all(
                t is None or isinstance(t, type)
                for t in (self.route_type, self.candidate_type)
            )
            or not all(isinstance(e, Enum) for e in enums)
            or type(self.meta) is not type(self.text)
            or self.meta is self.text
        ):
            raise ValueError("invalid hint bindings")


@dataclass(frozen=True)
class RoutedOutcome:
    """``rendered`` is the exact JobRef tuple whose candidates reached the
    renderer for the hint inside ``result``; it is ``()`` exactly when
    ``result`` is the unchanged original object."""

    result: ToolResult
    rendered: tuple[object, ...]


@dataclass
class HintAdapter:
    """Routed adapters (``bindings.route_type`` set) are immutable after
    construction (TEXTU-G3): assigning or deleting any field except
    ``last_meter`` raises, so an admitted call can never observe another
    carrier, flag, binding, tool or server stamp. A new arm is a new adapter
    (``dataclasses.replace``); a call keeps the adapter it was dispatched
    with. ``object.__setattr__`` bypasses this; in-process code is trusted
    (see job_awareness_hint_identity). Non-routed adapters stay mutable.
    """

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
    # TEXTU-01: the carrier that the routed bind rules accepted; None when the
    # bindings are not routed. Every routed call re-checks it.
    routed_carrier: Enum | None = field(default=None, init=False)

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
        routed = self.bindings.route_type is not None
        if not (routed and self._bind_routed()):
            try:
                self.schema = Schema(self.tool.output_schema)
            except (ValueError, TypeError, RecursionError):
                self.schema = None
            self.identity = (
                None if self.schema is None else producer_identity(self.tool)
            )
        object.__setattr__(self, "_sealed", routed)

    def __setattr__(self, name: str, value: object) -> None:
        if name != "last_meter" and self.__dict__.get("_sealed") is True:
            raise AttributeError(f"routed HintAdapter.{name} is immutable")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        if self.__dict__.get("_sealed") is True:
            raise AttributeError(f"routed HintAdapter.{name} is immutable")
        object.__delattr__(self, name)

    def _bind_routed(self) -> bool:
        """g5 §9.2 S-2 bind rules for routed (E2) mode; True when bound here.

        A tool without an output schema binds the ``NO_STRUCTURE`` sentinel
        and only the TEXT carrier (TEXT-U). TEXT on a tool that declares an
        output schema is rejected: with ``structuredContent`` present the
        client drops the extra text block (H-SC). Both fail closed at bind.
        """
        text = self.carrier is self.bindings.text
        if self.tool.output_schema is None:
            if not text:
                raise ValueError("NO_STRUCTURE tools bind only the TEXT carrier")
            self.schema = NO_STRUCTURE
            self.identity = producer_identity(self.tool, unstructured=True)
            self.routed_carrier = self.carrier
            return True
        if text:
            raise ValueError("routed TEXT needs a tool without an output schema")
        self.routed_carrier = self.carrier
        return False

    def routed_carrier_holds(self) -> bool:
        """TEXTU-01: the bind-time carrier rule still holds now.

        A schema-backed routed binding stays META and a ``NO_STRUCTURE``
        binding stays TEXT. A carrier reassigned after bind suppresses. The
        routed path checks it at admission, at render entry, before the
        render returns and after the worker returns; the lab emission checks
        it again before its EMITTED commit (TEXTU-G2-01).
        """
        binding = self.bindings
        expected = binding.text if self.schema is NO_STRUCTURE else binding.meta
        return self.carrier is expected and self.routed_carrier is expected

    def bind_server(self, server: object) -> None:
        """Bind the serverInfo stamp from the server that dispatches the tool.

        OBS-01: the byte reserve in ``_adapt`` trusts this stamp. A stale or
        smaller stamp lets a result that is too large on the wire receive a
        hint. A production composition must call this with the same server that
        registers the bound tool, after the server name and version are final.
        A server without a dict stamp binds None, which suppresses every hint.
        A routed adapter is immutable: give it ``server_info`` at construction.
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
        if not self._admitted(original, execution, routed=False):
            return original
        return await self.workers.run(
            lambda stop: self._adapt(original, stop), original
        )

    def _admitted(
        self, original: ToolResult, execution: object, *, routed: bool
    ) -> bool:
        """The shared gate of ``adapt`` and ``adapt_routed``; it consumes the
        receipt only after the cheap configuration checks passed. A
        ``NO_STRUCTURE`` tool is admitted on the routed path only, so ``adapt``
        treats it as before g5 (unknown schema: unchanged)."""
        unstructured = self.schema is NO_STRUCTURE
        if (
            self.enabled is not True
            or self.exclusive is not True
            or type(original) is not ToolResult
            or self.schema is None
            or self.identity is None
            or (unstructured and not routed)
            or (routed and not self.routed_carrier_holds())
        ):
            return False
        tool = claim(execution, original)
        if tool is not self.bound_tool or not native_tool(tool):
            return False
        producer = producer_identity(tool, self.identity, unstructured=unstructured)
        return producer is not None and producer == self.identity

    async def adapt_routed(
        self,
        original: ToolResult,
        *,
        execution: object = None,
        route: object = None,
    ) -> RoutedOutcome:
        """CA-2: ``adapt`` for one request-local SessionRoute (design §2.6).

        ``route`` must be exactly ``bindings.route_type``: the frozen route
        that the lab emission sequence builds after its reserve transaction.
        Its ``grant`` and ``jobs`` (1 to ``MAX_RENDERED`` exact ``job_type``
        values) are read once from the backing map and never stored;
        ``HintAdapter.grant`` and ``jobs`` are not used on this path. No
        request field can construct a route. The producer, receipt, schema,
        size and carrier rules are those of ``adapt``, with one g5 addition
        (§9.2 S-2, TEXT-U): a ``NO_STRUCTURE`` tool is served only here, only
        with the TEXT carrier, and only when the result has no
        ``structuredContent`` at all. The
        outcome names the exact jobs whose candidates the renderer received
        for the inserted hint (at most ``MAX_RENDERED``, each one in
        ``route.jobs``, in candidate order). Any doubt returns
        ``RoutedOutcome(original, ())``: the caller then resets or aborts
        every reserved job and never marks one emitted. ``adapt`` is
        unchanged and does not consult routes.
        """
        unchanged = RoutedOutcome(original, ())
        binding = self.bindings
        if (
            binding.route_type is None
            or binding.candidate_type is None
            or type(route) is not binding.route_type
        ):
            return unchanged
        try:  # the backing map of the exact type; no descriptor or hook runs
            data = object.__getattribute__(route, "__dict__")
        except AttributeError:  # a slotted route type has no backing map
            return unchanged
        if type(data) is not dict or "grant" not in data or "jobs" not in data:
            return unchanged
        grant, jobs = data["grant"], data["jobs"]
        if (
            type(jobs) is not tuple
            or not 1 <= len(jobs) <= MAX_RENDERED
            or not all(type(job) is binding.job_type for job in jobs)
        ):
            return unchanged
        if not self._admitted(original, execution, routed=True):
            return unchanged
        busy: tuple[ToolResult, tuple[object, ...]] = (original, ())
        result, rendered = await self.workers.run(
            lambda stop: self._render(original, stop, grant, jobs, routed=True), busy
        )
        if result is original or not rendered or not self.routed_carrier_holds():
            return unchanged
        return RoutedOutcome(result, rendered)

    def _adapt(self, original: ToolResult, stop: Event) -> ToolResult:
        return self._render(original, stop, self.grant, self.jobs, routed=False)[0]

    def _rendered(
        self, candidates: object, jobs: tuple[object, ...]
    ) -> tuple[object, ...] | None:
        """Jobs of the exact candidate tuple handed to the renderer, or None.

        Exact types run before any field access: a candidate must be exactly
        ``candidate_type`` and carry a ``job`` of exactly ``job_type`` that is
        one of the route jobs, with no repeats. ``rendered`` is therefore a
        subset of the reserved jobs by construction.
        """
        binding = self.bindings
        if type(candidates) is not tuple or not 1 <= len(candidates) <= MAX_RENDERED:
            return None
        rendered: list[object] = []
        for candidate in candidates:
            if type(candidate) is not binding.candidate_type:
                return None
            data = object.__getattribute__(candidate, "__dict__")
            if type(data) is not dict or "job" not in data:
                return None
            job = data["job"]
            if type(job) is not binding.job_type or job in rendered or job not in jobs:
                return None
            rendered.append(job)
        return tuple(rendered)

    def _render(
        self,
        original: ToolResult,
        stop: Event,
        grant: object,
        jobs: object,
        *,
        routed: bool,
    ) -> tuple[ToolResult, tuple[object, ...]]:
        binding = self.bindings
        meter = Meter(stop)
        self.last_meter = meter
        # TEXTU-G2-01: one carrier per call. Routed calls pin the bind-approved
        # carrier; every later decision uses only this local.
        if routed and not self.routed_carrier_holds():
            return original, ()
        carrier = self.routed_carrier if routed else self.carrier
        try:
            if type(self.server_info) is not dict:
                return original, ()
            stamp = {"io.modelcontextprotocol/serverInfo": self.server_info}
            walk({"_meta": stamp}, meter)
            overhead = meter.bytes  # Reserve the entire framework metadata wrapper.
            walk(original, meter, byte_limit=262144 - overhead)
            original_bytes = meter.bytes - (13 if original.meta is None else 0)
            meter.initial = False
            body = walk(original, meter, copy=True, byte_limit=262144 - overhead)
            if self.schema is NO_STRUCTURE:  # TEXT-U: no structure, routed TEXT
                if (
                    not routed
                    or carrier is not binding.text
                    or body["structuredContent"] is not None
                ):
                    return original, ()
            elif not self.schema.valid(body["structuredContent"], meter):
                return original, ()
            if (
                type(jobs) is not tuple
                or not 1 <= len(jobs) <= 8
                or not isinstance(grant, binding.grant_type)
                or not all(type(job) is binding.job_type for job in jobs)
                or not any(carrier is c for c in (binding.meta, binding.text))
            ):
                return original, ()
            observations = []
            scope = frozenset({binding.observe_scope})
            for job in jobs:
                meter.charge()
                if binding.check(grant, job, scope) is not binding.authorized:
                    return original, ()
                observed = binding.observe(grant, job)
                if type(observed) is not binding.success_type:
                    return original, ()
                record = observed.value
                if record.job != job:
                    return original, ()
                observations.append(record)
            candidates = binding.select(grant, tuple(observations))
            rendered: tuple[object, ...] = ()
            if routed:
                found = self._rendered(candidates, jobs)
                if found is None:
                    return original, ()
                rendered = found
            hint = binding.render(candidates, carrier)
            if type(hint) is not binding.hint_type:
                return original, ()
            data = object.__getattribute__(hint, "__dict__")
            if (
                not _fields(data, ("carrier", "text", "utf8_bytes"))
                or data["carrier"] is not carrier
                or type(data["text"]) is not str
                or type(data["utf8_bytes"]) is not int
                or not 1 <= data["utf8_bytes"] <= 512
            ):
                return original, ()
            text = data["text"]
            _string(text, meter, 263168, raw_limit=512)
            if len(text.encode("utf-8")) != data["utf8_bytes"]:
                return original, ()
            meter.charge(4096)  # fixed renderer and bounded carrier construction
            if carrier is binding.meta:
                meta = body["_meta"]
                if meta is None:
                    meta = body["_meta"] = {}
                if META_KEY in meta:
                    return original, ()
                meta[META_KEY] = text
            else:
                new = {"type": "text", "text": text, "annotations": None, "_meta": None}
                body["content"].append(new)
            walk(body, meter, byte_limit=263168 - overhead)
            if meter.bytes - original_bytes > 1024:
                return original, ()
            meter.charge(meter.bytes + meter.nodes + 32 * len(body["content"]))
            blocks: list[ContentBlock] = []
            blocks.extend(TextContent.model_construct(**c) for c in body["content"])
            result = ToolResult.model_construct(
                content=blocks,
                structured_content=body["structuredContent"],
                meta=body["_meta"],
            )
            if routed and not self.routed_carrier_holds():
                return original, ()  # drifted while the render ran
            return result, rendered
        except Exception:  # noqa: BLE001 - all awareness failures preserve the original
            return original, ()
