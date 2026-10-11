"""CA-2 routed-adapter fixtures: several synthetic jobs, routes and wire capture.

Everything here is synthetic. The emission ledger is a test double of the
design §2.6 lab ``emit`` table and its exact reserve/emit/reset/abort SQL;
the real lab ledger (S2, ``session_binding.py``) replaces it in S5.
"""

import asyncio
import hashlib
import json
import secrets
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import replace
from unittest.mock import patch

import httpx2
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.middleware import Middleware
from fastmcp.tools.base import Tool, ToolResult
from mcp.types import Implementation

from binnacle.features.commands.job_awareness.models import (
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
    "EmitLedger",
    "RoutedLab",
    "emission",
    "key_digest",
    "routed_app",
    "wire_call",
    "yield_",
]


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

    def routed(self, **options: object) -> HintAdapter:
        """A plain HintAdapter whose bindings name the candidate type."""
        synthetic = self.adapter(**options)
        bindings = replace(
            synthetic.bindings,
            route_type=SessionRoute,
            candidate_type=ReminderCandidate,
        )
        return HintAdapter(
            bindings=bindings,
            grant=synthetic.grant,
            jobs=synthetic.jobs,
            tool=synthetic.tool,
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
    schema: dict[str, object] = SCHEMA,
) -> tuple[FastMCP, list[object]]:
    """One witnessed synthetic tool; the carrier is the only adapter caller."""
    app = FastMCP("I2-2 synthetic only", version="synthetic")
    adapter.server_info = app._mcp_server.server_info_stamp

    def synthetic() -> ToolResult:
        return result if result is not None else original()

    tool = app.add_tool(
        witnessed_tool(synthetic, name="synthetic", output_schema=schema)
    )
    assert isinstance(tool, Tool)  # nosec B101 - pytest assertion
    bound = replace(adapter, tool=tool)
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


_DDL = """
CREATE TABLE emit (
  jobref         TEXT PRIMARY KEY,
  kd             TEXT NOT NULL,
  state          TEXT NOT NULL CHECK (state IN ('PENDING','RESERVED','EMITTED','ABORTED')),
  reservation_id TEXT NULL CHECK (reservation_id IS NULL OR length(reservation_id) = 32),
  reserved_ms    INTEGER NULL,
  final_ms       INTEGER NULL,
  version        INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
  CHECK ( (state = 'PENDING'  AND reservation_id IS NULL     AND reserved_ms IS NULL     AND final_ms IS NULL)
       OR (state = 'RESERVED' AND reservation_id IS NOT NULL AND reserved_ms IS NOT NULL AND final_ms IS NULL)
       OR (state IN ('EMITTED','ABORTED') AND final_ms IS NOT NULL) )
) STRICT;
"""
_RESERVE = (
    "UPDATE emit SET state='RESERVED', reservation_id=:rid, reserved_ms=:now,"
    " version=version+1 WHERE jobref=:j AND kd=:kd AND state='PENDING'"
)
_EMIT = (
    "UPDATE emit SET state='EMITTED', final_ms=:now, version=version+1"
    " WHERE jobref=:j AND kd=:kd AND state='RESERVED' AND reservation_id=:rid"
)
_RESET = (
    "UPDATE emit SET state='PENDING', reservation_id=NULL, reserved_ms=NULL,"
    " version=version+1"
    " WHERE jobref=:j AND kd=:kd AND state='RESERVED' AND reservation_id=:rid"
)
_ABORT = (
    "UPDATE emit SET state='ABORTED', final_ms=:now, version=version+1"
    " WHERE jobref=:j AND kd=:kd AND state='RESERVED' AND reservation_id=:rid"
)


class EmitLedger:
    """Test double of the §2.6 emission sequence around ``adapt_routed``.

    It keeps the exact design SQL and rowcount rules. The alloc ``LIVE``
    sub-select, the receipt filter and final validation belong to S2/S5.
    """

    def __init__(self, kd: str, jobs: tuple[JobRef, ...]):
        self.kd, self.jobs = kd, jobs
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.db.executescript(_DDL)
        for job in jobs:
            self.db.execute(
                "INSERT INTO emit(jobref,kd,state) VALUES(?,?,'PENDING')",
                (job.canonical_key, kd),
            )

    def state(self, job: JobRef) -> str:
        row = self.db.execute(
            "SELECT state FROM emit WHERE jobref=?", (job.canonical_key,)
        ).fetchone()
        return str(row[0])

    def counts(self) -> dict[str, int]:
        rows = self.db.execute("SELECT state, count(*) FROM emit GROUP BY state")
        return {str(state): int(count) for state, count in rows}

    def _rows(self, sql: str, jobs: tuple[JobRef, ...], rid: str) -> list[int]:
        return [
            self.db.execute(
                sql, {"j": job.canonical_key, "kd": self.kd, "rid": rid, "now": 1}
            ).rowcount
            for job in jobs
        ]

    def reserve(self, limit: int = 2) -> tuple[str, tuple[JobRef, ...]]:
        rid = secrets.token_hex(16)
        pending = sorted(
            (job for job in self.jobs if self.state(job) == "PENDING"),
            key=lambda job: job.canonical_key,
        )[:limit]
        self.db.execute("BEGIN IMMEDIATE")
        counts = self._rows(_RESERVE, tuple(pending), rid)
        self.db.execute("COMMIT")
        return rid, tuple(job for job, n in zip(pending, counts, strict=True) if n)

    def commit(
        self, rid: str, reserved: tuple[JobRef, ...], rendered: tuple[object, ...]
    ) -> bool:
        emitted = tuple(job for job in reserved if job in rendered)
        rest = tuple(job for job in reserved if job not in rendered)
        if len(emitted) != len(rendered):
            self.abort(rid, reserved)
            return False
        self.db.execute("BEGIN IMMEDIATE")
        counts = self._rows(_EMIT, emitted, rid) + self._rows(_RESET, rest, rid)
        if any(n != 1 for n in counts):
            self.db.execute("ROLLBACK")
            self.abort(rid, reserved)
            return False
        self.db.execute("COMMIT")
        return True

    def abort(self, rid: str, reserved: tuple[JobRef, ...]) -> None:
        self.db.execute("BEGIN IMMEDIATE")
        self._rows(_ABORT, reserved, rid)
        self.db.execute("COMMIT")


async def yield_() -> None:
    """A pause point that only yields to the event loop."""
    await asyncio.sleep(0)


async def emission(
    lab: RoutedLab,
    adapter: HintAdapter,
    ledger: EmitLedger,
    fence: Callable[[], Awaitable[object]] | None = None,
) -> ToolResult:
    """Reserve -> adapt_routed -> commit; the returned result is the transport's."""
    rid, reserved = ledger.reserve()
    if not reserved:
        return original()
    value = original()
    try:
        if fence is not None:
            await fence()
        _, outcome = await lab.call(adapter, lab.route(*reserved), value)
    except BaseException:
        ledger.abort(rid, reserved)
        raise
    if not set(outcome.rendered) <= set(reserved):
        ledger.abort(rid, reserved)
        return value
    if not ledger.commit(rid, reserved, outcome.rendered):
        return value
    return outcome.result
