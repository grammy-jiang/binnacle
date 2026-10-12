"""E2 S5 in-process synthetic composition (design §4.4, §4.6). TEST ONLY.

One lab phase = the real ``SessionLab`` (ReceiptStore v1 + lab ledger), the
real ``HintAdapter.adapt_routed`` with bindings over that lab, the S3 MCP
extraction (``route_call``) and the four lab tools on a native FastMCP app.
Chats are synthetic (session, subject) pairs sent as raw headers and
``params._meta`` over native streamable HTTP. Every value is registered
synthetic test data. Production composition never imports this module.
"""

import asyncio
import json
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

import httpx2
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import Middleware
from fastmcp.tools.base import Tool, ToolResult
from mcp.types import TextContent

from binnacle.features.commands.job_awareness import session_serving as serving
from binnacle.features.commands.job_awareness.hint_policy import select_candidates
from binnacle.features.commands.job_awareness.hint_render import render_hint
from binnacle.features.commands.job_awareness.models import (
    AuthorityDecision,
    HintCarrier,
    ReminderCandidate,
    RenderedHint,
    Scope,
    Success,
    VerifiedRunGrant,
)
from binnacle.features.commands.job_awareness.models import JobRef as JobRefType
from binnacle.features.commands.job_awareness.observation import JobObserver
from binnacle.features.commands.job_awareness.proofs import WorkerBudget
from binnacle.features.commands.job_awareness.session_emission import emit_hint
from binnacle.features.commands.job_awareness.session_lab import (
    LabConfig,
    LabError,
    SessionLab,
)
from binnacle.features.commands.job_awareness.session_route import (
    SESSION_META,
    SUBJECT_META,
    KeyDigest,
    RouteOutcome,
    RouteStatus,
    SessionRoute,
    route,
)
from binnacle.features.commands.job_awareness.session_snapshot import FrozenTemplate
from binnacle.mcp.job_awareness_hint import (
    HINT_FIELD,
    META_KEY,
    HintAdapter,
    HintBindings,
    witnessed_call,
    witnessed_tool,
)
from binnacle.mcp.job_awareness_session import lab_fields, route_call
from tests.contracts.job_awareness.synthetic_app import Workers
from tests.unit.core.job_awareness.session_support import (
    TEMPLATES,
    ManualClock,
    synthetic,
)

TC_TTL_MS = 3600000
SEND_GAP_MS = 180000
MARKER_HEADER = "x-ja-lab-marker"
NOTE = "Synthetic reference note."
NOTE_SCHEMA = {
    "type": "object",
    "properties": {"note": {"type": "string"}},
    "required": ["note"],
    "additionalProperties": False,
}
HINT_PREFIX = "[Binnacle job reminder] "
_CANONICAL = re.compile(r"ja1_[0-9a-f]{32}:[0-9a-f]{12}:g1_[0-9a-f]{32}")
_OUTCOME: ContextVar[RouteOutcome] = ContextVar("e2_outcome")
_ERRORS = frozenset(error.value for error in LabError)
_HTTP = [
    ("accept", "application/json, text/event-stream"),
    ("content-type", "application/json"),
    ("mcp-protocol-version", "2025-06-18"),
]


@dataclass(frozen=True)
class Chat:
    """One simulated conversation: a registered synthetic platform pair."""

    name: str
    session: str
    subject: str

    def headers(self) -> list[tuple[str, str]]:
        return [("x-openai-session", self.session), ("x-openai-subject", self.subject)]

    def meta(self) -> dict[str, object]:
        return {SESSION_META: self.session, SUBJECT_META: self.subject}


def chat(name: str, subject: str = "owner") -> Chat:
    """Fresh synthetic chat; one subject per account unless named otherwise."""
    return Chat(
        name, synthetic("session-" + name, 76), synthetic("subject-" + subject, 54)
    )


def hinted_keys(result: dict[str, Any]) -> list[str]:
    """Canonical JobRef keys carried by a META, TEXT or STRUCT hint of one
    result. A STRUCT JSON mirror (``content[0]``) is not counted twice."""
    texts = [(result.get("_meta") or {}).get(META_KEY) or ""]
    texts += [(result.get("structuredContent") or {}).get(HINT_FIELD) or ""]
    texts += [c.get("text", "") for c in result.get("content", [])[1:]]
    return [
        k for t in texts if t.startswith(HINT_PREFIX) for k in _CANONICAL.findall(t)
    ]


@dataclass
class Call:
    """One tools/call: the U/A/R evidence and the server's per-call log row."""

    chat: str
    tool: str
    arguments: dict[str, Any]
    raw: bytes
    result: dict[str, Any]
    row: dict[str, str]

    @property
    def error(self) -> str | None:
        if not self.result.get("isError"):
            return None
        return str(self.result["content"][0]["text"])

    @property
    def data(self) -> dict[str, Any]:
        return dict(self.result.get("structuredContent") or {})

    @property
    def hints(self) -> list[str]:
        return hinted_keys(self.result)


class Router(Middleware):
    """Lab router: extraction, binding, once-only emission, one log row."""

    def __init__(self, server: "E2Server") -> None:
        self.server = server

    async def on_call_tool(self, context: Any, call_next: Any) -> Any:
        server, lab = self.server, self.server.lab
        # TEXTU-G4-01: the arm of a call is the immutable adapter selected at
        # dispatch, captured before any await and never looked up again in
        # this call path, so an arm switch affects later calls only.
        adapter = server.adapter
        outcome = lab.bind(route_call(partial(route, lab.keyer)))
        request = get_http_request()
        marker = request.headers.get(MARKER_HEADER)
        token = _OUTCOME.set(outcome)
        mark = len(server.events)
        rendered: tuple[str, ...] = ()
        error: str | None = None
        try:
            if context.message.name == "fixture_unrelated_read":
                value, execution = await witnessed_call(call_next, context)
                result = await emit_hint(
                    lab, outcome, value, execution=execution, adapter=adapter
                )
                if result is not value:
                    rendered = tuple(server.handles(result))
            else:
                result = await call_next(context)
        except ToolError as exc:  # only the fixed lab vocabulary passes through
            error = str(exc) if str(exc) in _ERRORS else LabError.DENIED.value
        except Exception:  # noqa: BLE001 - never reflect a framework error
            error = LabError.DENIED.value
        finally:
            _OUTCOME.reset(token)
        hint = [e for e in server.events[mark:] if e.get("event") == "ja_hint"]
        key = lab.keyed(outcome)
        row = lab_fields(
            outcome,
            hint=bool(rendered),
            jobs=rendered,
            rid=str(hint[-1]["rid"]) if hint else None,
            emit_state=str(hint[-1]["emit_state"]) if hint else None,
            grant_remaining_ms=None if key is None else lab.grant_remaining_ms(key),
            marker=marker if marker == "scripted" else None,
        )
        server.rows.append(row)
        server.argument_log.append(json.dumps(context.message.arguments))
        if error is not None:
            raise ToolError(error)
        return result


@dataclass
class E2Server:
    """One E2 phase: its own ledger pair and epoch (design §2.5)."""

    phase: Path
    clock: ManualClock = field(default_factory=ManualClock)
    config: LabConfig = field(
        default_factory=lambda: LabConfig(ttl_ms=TC_TTL_MS, deferred_seal=True)
    )
    templates: dict[str, FrozenTemplate] = field(default_factory=lambda: TEMPLATES)
    carrier: HintCarrier = HintCarrier.META
    note: str = NOTE
    #: False = lab tool v2-U (g5 §9.2 S-2): no output schema, one text block.
    structured: bool = True
    #: Lab-only CV fixtures (g6 §9.3, e2_cprime): another advertised schema for
    #: the structured note, and the result the note tool returns for a note.
    note_schema: dict[str, Any] | None = None
    note_result: Callable[[str], ToolResult] | None = None
    faults: Callable[[str], None] | None = None

    def __post_init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.rows: list[dict[str, str]] = []
        self.argument_log: list[str] = []
        self.lab = SessionLab(
            self.phase,
            self.templates,
            self.clock.trusted(),
            config=self.config,
            faults=self.faults,
            events=self.events.append,
        )
        if not self.lab.start():
            raise RuntimeError("lab refused readiness")
        self.workers = Workers(WorkerBudget())
        self.app = FastMCP("E2 S5 synthetic only", version="synthetic")
        self.tool = self._register()
        self.adapter = self.build_adapter(enabled=True)
        self.app.add_middleware(Router(self))

    def _register(self) -> Tool:
        lab = self.lab

        async def fixture_start(slot: str) -> dict[str, str]:
            started = await lab.start_fixture(_OUTCOME.get(), slot)
            if isinstance(started, LabError):
                raise ToolError(started.value)
            return {"job": started}

        async def fixture_read(job: str, page: int, context: str = "") -> dict:
            if len(context) > 256:
                raise ToolError(LabError.DENIED.value)
            found = serving.read_page(lab, _OUTCOME.get(), job, page)
            if isinstance(found, LabError):
                raise ToolError(found.value)
            return found

        async def fixture_echo(
            job: str, values: list[str], context: str = ""
        ) -> dict[str, bool]:
            if len(context) > 256:
                raise ToolError(LabError.DENIED.value)
            found = serving.echo(lab, _OUTCOME.get(), job, values)
            if isinstance(found, LabError):
                raise ToolError(found.value)
            return found

        def fixture_unrelated_read(context: str = "") -> ToolResult:
            note = self.note
            if self.note_result is not None:
                return self.note_result(note)
            return ToolResult(
                content=[TextContent(type="text", text=note)],
                structured_content={"note": note} if self.structured else None,
            )

        for function in (fixture_start, fixture_read, fixture_echo):
            self.app.tool(function)
        tool = self.app.add_tool(
            witnessed_tool(
                fixture_unrelated_read,
                name="fixture_unrelated_read",
                output_schema=(self.note_schema or NOTE_SCHEMA)
                if self.structured
                else None,
            )
        )
        assert isinstance(tool, Tool)  # nosec B101 - pytest assertion
        return tool

    def build_adapter(self, *, enabled: bool) -> HintAdapter:
        """The real CA-2 adapter over this lab; ``enabled=False`` = control arm."""
        lab = self.lab
        observer = JobObserver(lab.authority, lab.snapshots.catalog, lab.clock.now)
        bindings = HintBindings(
            check=lambda grant, job, scopes: lab.authority.check(grant, job, scopes),
            observe=observer.observe,
            select=partial(
                select_candidates, authority=lab.authority, receipts=lab.receipts
            ),
            render=render_hint,
            hint_type=RenderedHint,
            grant_type=VerifiedRunGrant,
            job_type=JobRefType,
            success_type=Success,
            observe_scope=Scope.OBSERVE,
            authorized=AuthorityDecision.AUTHORIZED,
            meta=HintCarrier.META,
            text=HintCarrier.TEXT,
            route_type=SessionRoute,
            candidate_type=ReminderCandidate,
            struct=HintCarrier.STRUCT,
        )
        return HintAdapter(
            bindings=bindings,
            grant=None,
            jobs=(),
            tool=self.tool,
            workers=self.workers,
            server_info=self.app._mcp_server.server_info_stamp,
            enabled=enabled,
            carrier=self.carrier,
            exclusive=True,
        )

    def handles(self, result: ToolResult) -> list[str]:
        meta = result.meta or {}
        texts = [meta.get(META_KEY) or ""]
        texts += [(result.structured_content or {}).get(HINT_FIELD) or ""]
        texts += [getattr(block, "text", "") for block in result.content[1:]]
        keys = [k for t in texts for k in _CANONICAL.findall(t)]
        return ["j_" + key.split(":")[1] for key in keys]

    def outcome(self, who: Chat) -> RouteOutcome:
        """The bound route of a chat, as the router computes it."""
        meta = who.meta()
        return self.lab.bind(route(self.lab.keyer, [who.session], [who.subject], meta))

    def key(self, who: Chat) -> KeyDigest:
        outcome = route(self.lab.keyer, [who.session], [who.subject], who.meta())
        assert outcome.status is RouteStatus.UNBOUND and outcome.key  # nosec B101 - pytest assertion
        return outcome.key

    async def seal(self, who: Chat, handle: str) -> None:
        assert await serving.seal(self.lab, self.key(who), handle)  # nosec B101 - pytest assertion

    async def close(self, who: Chat) -> int:
        return await serving.close(self.lab, self.key(who))


class Wire:
    """Raw JSON-RPC ``tools/call`` posts through the native streamable HTTP app."""

    def __init__(self, server: E2Server, client: httpx2.AsyncClient) -> None:
        self.server, self.client = server, client
        self.calls: list[Call] = []
        self.sends = 0

    def send(self) -> None:
        """A new user send; sends are at least 180 s apart (§4.1)."""
        if self.sends:
            self.server.clock.advance(SEND_GAP_MS)
        self.sends += 1

    async def call(
        self,
        who: Chat | None,
        tool: str,
        arguments: dict[str, Any] | None = None,
        *,
        headers: list[tuple[str, str]] | None = None,
        meta: dict[str, object] | None = None,
        marker: bool = False,
    ) -> Call:
        params: dict[str, Any] = {"name": tool, "arguments": arguments or {}}
        sent_meta = meta if meta is not None else (who.meta() if who else None)
        if sent_meta is not None:
            params["_meta"] = sent_meta
        extra = headers if headers is not None else (who.headers() if who else [])
        if marker:
            extra = extra + [(MARKER_HEADER, "scripted")]
        body = {"jsonrpc": "2.0", "id": len(self.calls) + 1, "method": "tools/call"}
        response = await self.client.post(
            "/mcp", json=body | {"params": params}, headers=_HTTP + extra
        )
        assert response.status_code == 200, response.text[:200]  # nosec B101 - pytest assertion
        raw = response.content
        raw = raw[raw.index(b'"result":') + len(b'"result":') : -1]
        call = Call(
            who.name if who else "-",
            tool,
            dict(arguments or {}),
            raw,
            json.loads(raw),
            self.server.rows[-1],
        )
        self.calls.append(call)
        return call


@asynccontextmanager
async def running(server: E2Server) -> AsyncIterator[Wire]:
    http_app = server.app.http_app(stateless_http=True, json_response=True)
    async with http_app.router.lifespan_context(http_app):
        transport = httpx2.ASGITransport(app=http_app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://s") as c:
            try:
                yield Wire(server, c)
            finally:
                await server.workers.close()
                await asyncio.sleep(0)
