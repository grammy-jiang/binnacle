"""CA-2 routed-adapter fixtures: several synthetic jobs, routes and wire capture.

Everything here is synthetic. These fixtures exercise the adapter alone with
hand-built routes. The S4 in-memory ``emit`` double was replaced in S5 by the
real lab ledger: emission tests drive ``session_emission.emit_hint`` over the
real ``SessionLab`` (see ``e2_composition`` and ``test_hint_routed_emission``).
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from unittest.mock import patch

import httpx2
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.middleware import Middleware
from fastmcp.tools.base import Tool, ToolResult
from mcp.types import Implementation, TextContent

from binnacle.features.commands.job_awareness.models import (
    HintCarrier,
    JobRef,
    Observation,
    ObservationState,
    ReminderCandidate,
    VerifiedRunGrant,
)
from binnacle.features.commands.job_awareness.session_route import (
    KeyDigest,
    SessionKeyer,
    SessionRoute,
)
from binnacle.mcp.job_awareness_hint import (
    HintAdapter,
    RoutedOutcome,
    witnessed_call,
    witnessed_tool,
)
from tests.contracts.job_awareness.synthetic_app import SCHEMA, Lab, ok, original
from tests.contracts.job_awareness.test_hint_schema_support import executed

__all__ = [
    "RoutedLab",
    "key_digest",
    "routed_app",
    "text_only",
    "wire_call",
]


def text_only() -> ToolResult:
    """The TEXT-U result shape (g5 §9.2 S-2): one text block, no structure."""
    return ToolResult(
        content=[TextContent(type="text", text="Synthetic result")],
        meta={"existing": "kept"},
    )


def key_digest(seed: str = "a") -> KeyDigest:
    """A synthetic route key; the adapter never reads it."""
    keyer = SessionKeyer("e" * 32)
    return keyer.key("v1/" + seed * 76, "v1/" + seed * 54)


class RoutedLab(Lab):
    """The synthetic lab with ``count`` sealed jobs in one namespace."""

    def __init__(self, count: int = 4):
        super().__init__()
        self.jobs: tuple[JobRef, ...] = (self.job,) + tuple(
            replace(self.job, job_id=f"{index:012x}") for index in range(1, count)
        )
        for index, job in enumerate(self.jobs[1:], start=1):
            snapshot = replace(self.snapshot, job=job, seal_id=f"{index:032x}")
            ok(
                self.authority.store.controller_transaction(
                    lambda tx, snapshot=snapshot: tx.register_snapshot(
                        snapshot, self.data
                    )
                )
            )
            ok(
                self.catalog.register(
                    Observation(
                        job, ObservationState.TERMINAL, snapshot.terminal, snapshot
                    ),
                    self.payload,
                )
            )
        self.handle = self.consumer("c" * 32, jobs=self.jobs)

    def routed(self, *, structured: bool = True, **options: object) -> HintAdapter:
        """A plain HintAdapter whose bindings name the candidate type.

        ``structured=False`` binds a native tool without an output schema
        (TEXT-U, g5 §9.2 S-2).
        """
        synthetic = self.adapter(**options)
        tool = synthetic.tool
        if not structured:
            tool = Tool(name="synthetic", parameters={}, output_schema=None)
        bindings = replace(
            synthetic.bindings,
            route_type=SessionRoute,
            candidate_type=ReminderCandidate,
            struct=HintCarrier.STRUCT,
        )
        return HintAdapter(
            bindings=bindings,
            grant=synthetic.grant,
            jobs=synthetic.jobs,
            tool=tool,
            workers=synthetic.workers,
            server_info=synthetic.server_info,
            enabled=synthetic.enabled,
            carrier=synthetic.carrier,
            exclusive=synthetic.exclusive,
        )

    def route(
        self, *jobs: JobRef, grant: VerifiedRunGrant | None = None
    ) -> SessionRoute:
        handle = self.handle if grant is None else grant
        return SessionRoute(key_digest(), handle, tuple(jobs))

    async def call(
        self, adapter: HintAdapter, route: object, value: ToolResult | None = None
    ) -> tuple[ToolResult, RoutedOutcome]:
        """Direct routed call with a receipt for the bound tool."""
        value = original() if value is None else value
        receipt = executed(value, adapter.bound_tool)
        return value, await adapter.adapt_routed(value, execution=receipt, route=route)


class Carrier(Middleware):
    """Witness the dispatch, then call ``adapt`` or ``adapt_routed``."""

    def __init__(
        self,
        adapter: HintAdapter,
        route: Callable[[], object] | None,
        outcomes: list[object],
    ) -> None:
        self.adapter, self.route, self.outcomes = adapter, route, outcomes

    async def on_call_tool(self, context, call_next):
        value, execution = await witnessed_call(call_next, context)
        if self.route is None:
            result = await HintAdapter.adapt(self.adapter, value, execution=execution)
            self.outcomes.append(result)
            return result
        outcome = await self.adapter.adapt_routed(
            value, execution=execution, route=self.route()
        )
        self.outcomes.append(outcome)
        return outcome.result


def routed_app(
    adapter: HintAdapter,
    result: ToolResult | None = None,
    *,
    route: Callable[[], object] | None = None,
    schema: dict[str, object] | None = SCHEMA,
) -> tuple[FastMCP, list[object]]:
    """One witnessed synthetic tool; the carrier is the only adapter caller.

    ``schema=None`` registers the tool without an output schema (TEXT-U).
    """
    app = FastMCP("I2-2 synthetic only", version="synthetic")

    def synthetic() -> ToolResult:
        return result if result is not None else original()

    tool = app.add_tool(
        witnessed_tool(synthetic, name="synthetic", output_schema=schema)
    )
    assert isinstance(tool, Tool)  # nosec B101 - pytest assertion
    # Routed adapters are immutable: the stamp is bound by a new adapter.
    bound = replace(adapter, tool=tool, server_info=app._mcp_server.server_info_stamp)
    outcomes: list[object] = []
    app.add_middleware(Carrier(bound, route, outcomes))
    return app, outcomes


async def wire_call(app, protocol, *, headers=None, meta=None):
    """Native streamable-HTTP call; return the parsed result and raw bytes."""
    http_app = app.http_app(stateless_http=True, json_response=True)
    raw: list[bytes] = []

    async def record(response):
        body = await response.aread()
        if body and "content" in json.loads(body).get("result", {}):
            raw.append(body[body.index(b'"result":') + len(b'"result":') : -1])

    def factory(**kwargs):
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=http_app),
            event_hooks={"response": [record]},
            **kwargs,
        )

    async with http_app.router.lifespan_context(http_app):
        transport = StreamableHttpTransport(
            "http://synthetic/mcp",
            httpx_client_factory=factory,
            headers={"authorization": "Bearer synthetic-shared", **(headers or {})},
        )
        with patch("mcp.client.session.LATEST_HANDSHAKE_VERSION", "2025-06-18"):
            async with Client(
                transport,
                mode="legacy" if protocol == "2025-06-18" else protocol,
                cache=False,
                client_info=Implementation(name="synthetic", version="0"),
            ) as client:
                result = await client.call_tool(
                    "synthetic", meta=meta, raise_on_error=False
                )
    assert len(raw) == 1  # nosec B101 - pytest assertion
    return result, raw[0]


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
