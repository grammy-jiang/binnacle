"""E2 S3: MCP-side session extraction over native ASGI; digest-only logs.

Every session and subject value here is a synthetic, well-formed stand-in
generated per test run. No real platform value is used or stored.
"""

import json
import logging
import secrets
from contextvars import copy_context
from enum import Enum
from functools import partial
from types import SimpleNamespace

import httpx2
import pytest
import uvloop
from fastmcp import Client, FastMCP
from fastmcp.server.dependencies import fastmcp_request_ctx, get_http_request
from fastmcp.server.middleware import Middleware
from starlette.datastructures import Headers

from binnacle.features.commands.job_awareness import session_route as core
from binnacle.features.commands.job_awareness.session_route import (
    RouteOutcome,
    RouteStatus,
    SessionKeyer,
    route,
)
from binnacle.mcp import job_awareness_session as lab
from binnacle.mcp.job_awareness_session import (
    LAB_MARKERS,
    RAW_VALUE,
    LabLogError,
    format_fields,
    lab_fields,
    raw_value_hits,
    route_call,
    route_fields,
)

LOGGER = logging.getLogger("binnacle.ja_lab.synthetic")
EPOCH = "e" * 32


def session() -> str:
    return "v1/" + secrets.token_urlsafe(57)


def subject() -> str:
    return "v1/" + secrets.token_urlsafe(40)[:54]


class Recorder(Middleware):
    """The lab's extraction point: one outcome and one log line per call."""

    def __init__(self, keyer: SessionKeyer, *, leak: bool = False) -> None:
        self.keyer, self.leak = keyer, leak
        self.outcomes: list[RouteOutcome] = []
        self.same_request: list[bool] = []

    async def on_call_tool(self, context, call_next):
        outcome = route_call(partial(route, self.keyer))
        bound = fastmcp_request_ctx.get()
        if bound is not None and bound.request is not None:
            self.same_request.append(get_http_request() is bound.request)
        self.outcomes.append(outcome)
        LOGGER.info("ja_call %s", format_fields(route_fields(outcome)))
        # The A stream (model tool-call arguments) is logged and scanned too.
        LOGGER.info("ja_args %s", json.dumps(context.message.arguments))
        if self.leak:  # negative control only: a deliberately unsafe logger
            values = bound.request.headers.getlist("x-openai-session")
            LOGGER.info("leaky header=%s", values)
        return await call_next(context)


def lab_app(keyer: SessionKeyer, **options) -> tuple[FastMCP, Recorder]:
    app = FastMCP("E2 S3 synthetic only", version="synthetic")

    @app.tool
    def fixture_unrelated_read(context: str = "") -> dict[str, bool]:
        return {"ok": True}

    recorder = Recorder(keyer, **options)
    app.add_middleware(recorder)
    return app, recorder


HEADERS = [
    ("accept", "application/json, text/event-stream"),
    ("content-type", "application/json"),
    ("mcp-protocol-version", "2025-06-18"),
]


async def post(app, calls):
    """Raw JSON-RPC tools/call posts; header lists keep duplicates and bytes."""
    http_app = app.http_app(stateless_http=True, json_response=True)
    bodies = []
    async with http_app.router.lifespan_context(http_app):
        transport = httpx2.ASGITransport(app=http_app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://s") as c:
            for index, (headers, meta, arguments) in enumerate(calls):
                params: dict[str, object] = {
                    "name": "fixture_unrelated_read",
                    "arguments": arguments or {},
                }
                if meta is not None:
                    params["_meta"] = meta
                response = await c.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": index + 1,
                        "method": "tools/call",
                        "params": params,
                    },
                    headers=HEADERS + list(headers),
                )
                assert response.status_code == 200, response.text[:200]  # nosec B101 - pytest assertion
                bodies.append(response.text)
    return bodies


def pair(s=None, u=None, *, header_names=("x-openai-session", "x-openai-subject")):
    s, u = s or session(), u or subject()
    headers = [(header_names[0], s), (header_names[1], u)]
    return headers, {"openai/session": s, "openai/subject": u}


def run(app, calls):
    return uvloop.run(post(app, calls))


def test_valid_pair_is_keyed_and_logged_as_prefix(caplog):
    keyer = SessionKeyer(EPOCH)
    app, recorder = lab_app(keyer)
    headers, meta = pair()
    caplog.set_level(logging.DEBUG)
    run(app, [(headers, meta, None)])
    (outcome,) = recorder.outcomes
    expected = keyer.key(meta["openai/session"], meta["openai/subject"])
    assert outcome == RouteOutcome(RouteStatus.UNBOUND, expected)  # nosec B101 - pytest assertion
    assert recorder.same_request == [True]  # nosec B101 - pytest assertion
    line = next(r.getMessage() for r in caplog.records if "ja_call" in r.getMessage())
    assert line == f"ja_call ja_route=UNBOUND ja_key={expected.d_sess[:16]}"  # nosec B101 - pytest assertion


def test_header_name_casing_is_irrelevant():
    keyer = SessionKeyer(EPOCH)
    app, recorder = lab_app(keyer)
    s, u = session(), subject()
    calls = [
        pair(s, u),
        pair(s, u, header_names=("X-OpenAI-Session", "X-OpenAI-Subject")),
        pair(s, u, header_names=("X-OPENAI-SESSION", "x-OpenAI-subject")),
    ]
    run(app, [(h, m, None) for h, m in calls])
    keys = {outcome.key for outcome in recorder.outcomes}
    assert len(keys) == 1 and None not in keys  # nosec B101 - pytest assertion


def test_duplicate_headers_fail_closed_even_when_equal():
    app, recorder = lab_app(SessionKeyer(EPOCH))
    s, u = session(), subject()
    headers, meta = pair(s, u)
    calls = [
        (headers + [("x-openai-session", s)], meta, None),
        (headers + [("X-OpenAI-Session", session())], meta, None),
        (headers + [("x-openai-subject", u)], meta, None),
        ([("x-openai-session", f"{s}, {s}"), headers[1]], meta, None),
    ]
    run(app, calls)
    statuses = [outcome.status for outcome in recorder.outcomes]
    assert statuses == [RouteStatus.NO_SESSION] * 3 + [RouteStatus.MALFORMED]  # nosec B101 - pytest assertion


def test_missing_inputs():
    app, recorder = lab_app(SessionKeyer(EPOCH))
    headers, meta = pair()
    calls = [
        ([], meta, None),
        (headers[:1], meta, None),
        (headers[1:], meta, None),
        (headers, None, None),
        (headers, {"openai/session": meta["openai/session"]}, None),
        (headers, {"openai/subject": meta["openai/subject"]}, None),
        (headers, {}, None),
    ]
    run(app, calls)
    statuses = [outcome.status for outcome in recorder.outcomes]
    assert statuses == [RouteStatus.NO_SESSION] * 3 + [RouteStatus.NO_META] * 4  # nosec B101 - pytest assertion


@pytest.mark.parametrize(
    "value", [5, None, True, 1.5, [], {}, ["v1/x"], {"v": "v1/x"}, "", " "]
)
def test_meta_non_string_or_empty_values_are_malformed(value):
    app, recorder = lab_app(SessionKeyer(EPOCH))
    headers, meta = pair()
    run(
        app,
        [
            (headers, {**meta, "openai/session": value}, None),
            (headers, {**meta, "openai/subject": value}, None),
        ],
    )
    for outcome in recorder.outcomes:
        assert outcome.status is RouteStatus.MALFORMED and outcome.key is None  # nosec B101 - pytest assertion


def test_header_encoding_is_never_decoded_or_normalized():
    app, recorder = lab_app(SessionKeyer(EPOCH))
    s, u = session(), subject()
    headers, meta = pair(s, u)
    latin = s[:-1].encode() + b"\xe9"
    calls = [
        ([(b"x-openai-session", latin), headers[1]], meta, None),
        ([("x-openai-session", s.lower()), headers[1]], meta, None),
        ([("x-openai-session", s[:-1] + "="), headers[1]], meta, None),
        ([("x-openai-session", "v1%2F" + s[3:]), headers[1]], meta, None),
        ([("x-openai-session", s + "A"), headers[1]], meta, None),
    ]
    run(app, calls)
    statuses = [outcome.status for outcome in recorder.outcomes]
    # Lower-casing keeps the grammar, so only the comparison catches it.
    assert statuses == [  # nosec B101 - pytest assertion
        RouteStatus.MALFORMED,
        RouteStatus.MISMATCH if s.lower() != s else RouteStatus.UNBOUND,
        RouteStatus.MALFORMED,
        RouteStatus.MALFORMED,
        RouteStatus.MALFORMED,
    ]
    # A non-ASCII value is not flagged as a format change; a grammar miss is.
    assert recorder.outcomes[0].format_change is False  # nosec B101 - pytest assertion
    assert recorder.outcomes[2].format_change is True  # nosec B101 - pytest assertion


def test_header_and_meta_must_agree():
    app, recorder = lab_app(SessionKeyer(EPOCH))
    headers, meta = pair()
    calls = [
        (headers, {**meta, "openai/session": session()}, None),
        (headers, {**meta, "openai/subject": subject()}, None),
    ]
    run(app, calls)
    assert [o.status for o in recorder.outcomes] == [RouteStatus.MISMATCH] * 2  # nosec B101 - pytest assertion


def test_arguments_and_client_fields_are_never_identity(caplog):
    """Selector-like arguments, X-Request-Id and clientInfo are not read."""
    app, recorder = lab_app(SessionKeyer(EPOCH))
    s, u = session(), subject()
    argument = json.dumps({"openai/session": s, "openai/subject": u})
    caplog.set_level(logging.DEBUG)
    run(
        app,
        [
            ([("x-request-id", s)], {"chat_id": s}, {"context": argument}),
            ([("x-openai-session-id", s)], None, {"context": s}),
        ],
    )
    assert [o.status for o in recorder.outcomes] == [RouteStatus.NO_SESSION] * 2  # nosec B101 - pytest assertion
    # The argument log carries the seeded bytes: the scan sees them, and only
    # the exact registered synthetic values are allowed (A2-04).
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert set(raw_value_hits(text)) == {s, u}  # nosec B101 - pytest assertion
    assert raw_value_hits(text, allowed={s, u}) == []  # nosec B101 - pytest assertion
    assert raw_value_hits(text, allowed={s}) == [u]  # nosec B101 - pytest assertion


def test_in_memory_transport_has_no_session():
    app, recorder = lab_app(SessionKeyer(EPOCH))
    _, meta = pair()

    async def call():
        async with Client(app) as client:
            await client.call_tool("fixture_unrelated_read", meta=meta)

    uvloop.run(call())
    assert recorder.outcomes == [RouteOutcome(RouteStatus.NO_SESSION)]  # nosec B101 - pytest assertion


def test_interleaved_sessions_are_stable_and_distinct():
    keyer = SessionKeyer(EPOCH)
    app, recorder = lab_app(keyer)
    first, second = pair(), pair()
    run(app, [(*first, None), (*second, None), (*first, None), (*second, None)])
    keys = [outcome.key for outcome in recorder.outcomes]
    assert keys[0] == keys[2] and keys[1] == keys[3] and keys[0] != keys[1]  # nosec B101 - pytest assertion
    assert keys[0].d_subj != keys[1].d_subj  # nosec B101 - pytest assertion
    keyer.rotate("f" * 32)
    run(app, [(*first, None)])
    rotated = recorder.outcomes[-1].key
    assert rotated.epoch == "f" * 32 and rotated.d_sess != keys[0].d_sess  # nosec B101 - pytest assertion


def test_logs_and_evidence_carry_no_raw_value(caplog):
    keyer = SessionKeyer(EPOCH)
    app, recorder = lab_app(keyer)
    caplog.set_level(logging.DEBUG)
    good, other = pair(), pair()
    calls = [
        (*good, None),
        (good[0], other[1], None),
        (good[0] + good[0][:1], good[1], None),
        (good[0], None, None),
        (*other, None),
    ]
    bodies = run(app, calls)
    evidence = [
        {**route_fields(o), "outcome": repr(o), "key": repr(o.key)}
        for o in recorder.outcomes
    ]
    exported = "\n".join(
        [record.getMessage() for record in caplog.records]
        + [json.dumps(evidence)]
        + bodies
    )
    assert "ja_call" in exported  # nosec B101 - pytest assertion
    assert raw_value_hits(exported) == []  # nosec B101 - pytest assertion
    for value in (good[1]["openai/session"], good[1]["openai/subject"]):
        assert value not in exported and value[3:43] not in exported  # nosec B101 - pytest assertion


def test_raw_scan_negative_controls(caplog):
    app, _ = lab_app(SessionKeyer(EPOCH), leak=True)
    caplog.set_level(logging.DEBUG)
    headers, meta = pair()
    run(app, [(headers, meta, None)])
    leaked = "\n".join(record.getMessage() for record in caplog.records)
    s = meta["openai/session"]
    assert raw_value_hits(leaked) == [s]  # nosec B101 - pytest assertion
    assert raw_value_hits(leaked, allowed={s}) == []  # nosec B101 - pytest assertion
    assert raw_value_hits(s + "x", allowed={s}) == [s + "x"]  # nosec B101 - pytest assertion
    assert raw_value_hits(s[:43]) == [s[:43]] and raw_value_hits(s[:42]) == []  # nosec B101 - pytest assertion
    assert RAW_VALUE.pattern == r"v1/[A-Za-z0-9_-]{40,}"  # nosec B101 - pytest assertion


def test_lab_fields_are_validated():
    keyed = RouteOutcome(
        RouteStatus.BOUND, SessionKeyer(EPOCH).key(session(), subject())
    )
    fields = lab_fields(
        keyed,
        hint=True,
        jobs=("j_" + "a" * 12, "j_" + "b" * 12),
        rid="c" * 32,
        emit_state="EMITTED",
        grant_remaining_ms=1200,
        marker="scripted",
    )
    assert (
        fields
        == {  # nosec B101 - pytest assertion
            "ja_route": "BOUND",
            "ja_key": keyed.key.d_sess[:16],
            "ja_hint": "1",
            "ja_job": f"j_{'a' * 12},j_{'b' * 12}",
            "rid": "c" * 32,
            "emit_state": "EMITTED",
            "grant_remaining_ms": "1200",
            "ja_lab_marker": "scripted",
        }
    )
    assert LAB_MARKERS == {"scripted"}  # nosec B101 - pytest assertion
    malformed = RouteOutcome(RouteStatus.MALFORMED, format_change=True)
    assert route_fields(malformed) == {  # nosec B101 - pytest assertion
        "ja_route": "MALFORMED",
        "ja_key": "-",
        "ja_format_change": "1",
    }
    bad = [
        {"hint": 1},
        {"jobs": ("ja1_" + "a" * 32,)},
        {"jobs": ("j_" + "a" * 12,) * 9},
        {"jobs": (session(),)},
        {"rid": "C" * 32},
        {"rid": 5},
        {"emit_state": "LIVE"},
        {"emit_state": ["EMITTED"]},
        {"grant_remaining_ms": -1},
        {"grant_remaining_ms": True},
        {"marker": "operator"},
        {"marker": ["scripted"]},
    ]
    for options in bad:
        with pytest.raises(LabLogError):
            lab_fields(keyed, **options)
    for fields in (
        {"ja_key": "v1/" + "a" * 40},
        {"ja_key": "a b"},
        {"raw": "x"},
        {"ja_key": ""},
    ):
        with pytest.raises(LabLogError):
            format_fields(fields)
    with pytest.raises(LabLogError):
        route_fields(object())


def test_route_call_outside_or_with_odd_context():
    keyer = SessionKeyer(EPOCH)
    classify = partial(route, keyer)
    assert route_call(classify) == RouteOutcome(RouteStatus.NO_SESSION)  # nosec B101 - pytest assertion
    headers, meta = pair()
    raw = [(name.encode(), value.encode()) for name, value in headers]
    request = SimpleNamespace(headers=Headers(raw=raw))
    for bound, expected in (
        (SimpleNamespace(request=None, meta=meta), RouteStatus.NO_SESSION),
        (SimpleNamespace(request=request, meta="x"), RouteStatus.NO_META),
        (SimpleNamespace(request=request, meta=list(meta)), RouteStatus.NO_META),
        (SimpleNamespace(request=request, meta=meta), RouteStatus.UNBOUND),
    ):

        def inside(bound=bound):
            fastmcp_request_ctx.set(bound)
            return route_call(classify)

        assert copy_context().run(inside).status is expected  # nosec B101 - pytest assertion


def test_mirrors_of_core_names_are_exact():
    assert lab.SESSION_HEADER == core.SESSION_HEADER  # nosec B101 - pytest assertion
    assert lab.SUBJECT_HEADER == core.SUBJECT_HEADER  # nosec B101 - pytest assertion
    assert lab.ROUTE_STATUSES == {status.value for status in RouteStatus}  # nosec B101 - pytest assertion
    assert core.LOG_KEY_HEX == 16  # nosec B101 - pytest assertion


def test_structural_outcomes_fail_closed():
    """Only a fixed status vocabulary and a 16-hex key ever reach a field."""
    key = SimpleNamespace(log_key="a" * 16)
    alien = Enum("Alien", {"BOUND": "PWNED"})
    for outcome, name in (
        (SimpleNamespace(status=alien.BOUND, key=key, format_change=False), "ja_route"),
        (SimpleNamespace(status="BOUND", key=key, format_change=False), "ja_route"),
        (SimpleNamespace(status=RouteStatus.BOUND, key=None), "ja_route"),
        (
            SimpleNamespace(
                status=RouteStatus.BOUND,
                key=SimpleNamespace(log_key="v1/" + "a" * 40),
                format_change=False,
            ),
            "ja_key",
        ),
        (
            SimpleNamespace(
                status=RouteStatus.BOUND,
                key=SimpleNamespace(log_key="A" * 16),
                format_change=False,
            ),
            "ja_key",
        ),
        (
            SimpleNamespace(status=RouteStatus.BOUND, key=key, format_change=1),
            "ja_format_change",
        ),
    ):
        with pytest.raises(LabLogError, match=name):
            route_fields(outcome)
    good = SimpleNamespace(status=RouteStatus.BOUND, key=key, format_change=False)
    assert route_fields(good) == {"ja_route": "BOUND", "ja_key": "a" * 16}  # nosec B101 - pytest assertion
