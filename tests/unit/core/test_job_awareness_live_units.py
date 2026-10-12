"""Unit tests of the production Job Awareness ledger, renderer and carrier."""

import json
from types import SimpleNamespace

import pytest
from fastmcp.tools.base import ToolResult
from mcp.types import TextContent

from binnacle.features.commands.job_awareness.session_route import (
    RouteOutcome,
    RouteStatus,
    SessionKeyer,
    route,
)
from binnacle.mcp import job_awareness_live as live
from binnacle.mcp import job_awareness_route, job_awareness_session
from binnacle.mcp.job_awareness_live_ledger import (
    ACKED,
    EMITTED,
    MAX_JOBS_PER_KEY,
    MAX_KEYS,
    PENDING,
    TTL_S,
    Ledger,
)

A, B = (
    "a" * 32 + ":" + "b" * 32 + ":" + "c" * 32,
    "a" * 32 + ":" + "b" * 32 + ":" + "d" * 32,
)
STAMP = {"name": "binnacle", "version": "1.0.1"}
SCHEMA = {
    "type": "object",
    "properties": {"path": {"type": "string"}, "count": {"type": "integer"}},
    "required": ["path"],
}
HINT = "[Binnacle job reminder] synthetic"


def job(n: int) -> str:
    return f"{n:012x}"


# ---------------------------------------------------------------- ledger


def test_ledger_binds_per_key_and_never_crosses():
    ledger = Ledger()
    assert ledger.bind(A, job(1), 0.0) == "bound"
    assert ledger.bind(A, job(1), 0.0) == "duplicate"
    assert ledger.pending(A, 1.0) == (job(1),)
    assert ledger.pending(B, 1.0) == ()
    assert ledger.state(B, job(1), 1.0) is None
    assert not ledger.ack(B, job(1), 1.0)
    assert not ledger.emitted(B, (job(1),), 1.0)
    assert ledger.state(A, job(1), 1.0) == PENDING


@pytest.mark.parametrize("bad", ["", "XYZ", "0123456789abc", "0123456789AB", 7, None])
def test_ledger_refuses_invalid_job_ids(bad):
    assert Ledger().bind(A, bad, 0.0) == "invalid"


def test_ledger_states_are_once_only():
    ledger = Ledger()
    ledger.bind(A, job(1), 0.0)
    ledger.bind(A, job(2), 0.0)
    assert ledger.emitted(A, (job(1),), 1.0)
    assert ledger.state(A, job(1), 1.0) == EMITTED
    assert not ledger.emitted(A, (job(1),), 1.0)
    assert not ledger.emitted(A, (job(1), job(2)), 1.0)  # all or nothing
    assert ledger.state(A, job(2), 1.0) == PENDING
    assert ledger.ack(A, job(2), 1.0) and ledger.state(A, job(2), 1.0) == ACKED
    assert not ledger.ack(A, job(2), 1.0)
    assert ledger.pending(A, 1.0) == ()


def test_ledger_caps_rows_per_key_and_drops_done_rows_first():
    ledger = Ledger()
    for n in range(MAX_JOBS_PER_KEY):
        assert ledger.bind(A, job(n), 0.0) == "bound"
    assert ledger.bind(A, job(99), 0.0) == "key_full"
    ledger.ack(A, job(3), 0.0)
    assert ledger.bind(A, job(99), 0.0) == "bound"
    assert ledger.state(A, job(3), 0.0) is None
    assert len(ledger.pending(A, 0.0)) == MAX_JOBS_PER_KEY


def test_ledger_caps_keys_and_expires_rows():
    ledger = Ledger()
    keys = [f"{n:032x}:{'b' * 32}:{'c' * 32}" for n in range(MAX_KEYS + 1)]
    for key in keys:
        ledger.bind(key, job(1), 0.0)
    assert ledger.pending(keys[0], 0.0) == ()  # least recently used dropped
    assert ledger.pending(keys[-1], 0.0) == (job(1),)
    assert ledger.pending(keys[-1], TTL_S + 1) == ()
    assert len(ledger) == MAX_KEYS - 1


def test_ledger_forget_drops_the_row():
    ledger = Ledger()
    ledger.bind(A, job(1), 0.0)
    ledger.forget(A, job(1), 0.0)
    ledger.forget(B, job(1), 0.0)
    assert len(ledger) == 0


# ---------------------------------------------------------------- render


def test_render_one_and_two_jobs_with_fixed_words():
    one = live.render_hint(((job(1), {"exit_code": 0, "signal": None}),))
    assert one.startswith(live.HINT_PREFIX) and "exit_code 0" in one
    two = live.render_hint(
        ((job(1), {"exit_code": None, "signal": 15}), (job(2), {"exit_code": "x"}))
    )
    assert "signal 15" in two and "exit status unknown" in two
    assert len(two.encode()) <= 512


@pytest.mark.parametrize(
    "finished",
    [
        (),
        ((job(1), {}),) * 2,
        tuple((job(n), {}) for n in range(3)),
        (("not-a-job", {}),),
        [(job(1), {})],
    ],
)
def test_render_refuses_bad_input(finished):
    assert live.render_hint(finished) is None


# ---------------------------------------------------------------- schema


def test_advertised_schema_adds_only_the_optional_field():
    advertised = live.advertised_schema(SCHEMA)
    assert advertised["properties"]["job_awareness_hint"] == {
        "type": "string",
        "maxLength": 512,
    }
    assert list(advertised["properties"])[-1] == "job_awareness_hint"
    assert advertised["required"] == ["path"]
    assert "job_awareness_hint" not in SCHEMA["properties"]  # input untouched
    assert live.declares_open_hint_field(advertised)


@pytest.mark.parametrize(
    "schema",
    [
        None,
        {"type": "array"},
        {"type": "object"},
        {**SCHEMA, "additionalProperties": False},
        {**SCHEMA, "description": "unsupported keyword"},
        {"type": "object", "properties": {"job_awareness_hint": {"type": "string"}}},
    ],
)
def test_advertised_schema_refuses_unsupported_shapes(schema):
    assert live.advertised_schema(schema) is None


@pytest.mark.parametrize(
    "field",
    [
        {"type": "string"},
        {"type": "string", "maxLength": 511},
        {"type": "string", "maxLength": 512, "description": "x"},
    ],
)
def test_open_field_rule_is_the_reviewed_exact_rule(field):
    schema = {"type": "object", "properties": {"job_awareness_hint": field}}
    assert not live.declares_open_hint_field(schema)
    required = {
        "type": "object",
        "properties": {"job_awareness_hint": {"type": "string", "maxLength": 512}},
        "required": ["job_awareness_hint"],
    }
    assert not live.declares_open_hint_field(required)


# ---------------------------------------------------------------- carrier


def result(structured, text="Listed 1 entry.", **extra):
    return ToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=structured,
        **extra,
    )


def advertised():
    return live.advertised_schema(SCHEMA)


def test_insert_keeps_plain_text_and_the_original_object():
    original = result({"path": "/tmp", "count": 1})
    hinted = live.insert_struct_hint(original, HINT, advertised(), STAMP)
    assert type(hinted) is ToolResult and hinted is not original
    assert hinted.structured_content == {
        "path": "/tmp",
        "count": 1,
        "job_awareness_hint": HINT,
    }
    assert hinted.content[0].text == "Listed 1 entry."
    assert original.structured_content == {"path": "/tmp", "count": 1}


def test_insert_rewrites_one_exact_mirror_in_its_own_format():
    structured = {"path": "/tmp", "count": 1}
    compact = json.dumps(structured, separators=(",", ":"))
    hinted = live.insert_struct_hint(
        result(structured, text=compact), HINT, advertised(), STAMP
    )
    assert json.loads(hinted.content[0].text)["job_awareness_hint"] == HINT


@pytest.mark.parametrize(
    ("original", "schema", "stamp", "reason"),
    [
        ("not a result", None, STAMP, "result_type"),
        (result({"path": "/x"}, is_error=True), None, STAMP, "error_result"),
        (result(None), None, STAMP, "no_structure"),
        (result({"path": "/x"}), None, None, "stamp"),
        (result({"path": "/x"}), SCHEMA, STAMP, "schema"),
        (result({"path": 7}), None, STAMP, "invalid_original"),
        (result({"path": "/x", "job_awareness_hint": "old"}), None, STAMP, "insert"),
        (  # STRUCT-01: a text that matches both mirror formats is ambiguous
            result({}, text="{}"),
            live.advertised_schema({"type": "object", "properties": {}}),
            STAMP,
            "unsupported",
        ),
        (  # a JSON object equal to the structure in an unknown format
            result({"path": "/x"}, text='{ "path" :  "/x" }'),
            None,
            STAMP,
            "unsupported",
        ),
        (result({"path": "/x" * 200000}), None, STAMP, "unsupported"),
    ],
)
def test_insert_suppresses_every_doubt(original, schema, stamp, reason):
    schema = advertised() if schema is None else schema
    assert live.insert_struct_hint(original, HINT, schema, stamp) == reason


def test_insert_enforces_the_hint_size_and_growth_caps():
    longest = "x" * 512
    plain = result({"path": "/x"})
    mirrored = result({"path": "/x"}, text=json.dumps({"path": "/x"}))
    assert (
        type(live.insert_struct_hint(plain, longest, advertised(), STAMP)) is ToolResult
    )
    # field plus re-serialized mirror: more than 1024 bytes of growth
    assert live.insert_struct_hint(mirrored, longest, advertised(), STAMP) == "growth"
    assert (
        live.insert_struct_hint(plain, "x" * 513, advertised(), STAMP) == "unsupported"
    )


# ---------------------------------------------------------------- logs, route


def test_log_lines_refuse_raw_values_and_bad_characters():
    assert live._line("ja_hint", outcome="emitted") == "event=ja_hint outcome=emitted"
    assert live._line("ja_hint", key="v1/" + "A" * 76) is None
    assert live._line("ja_hint", key="has space") is None
    assert live._line("ja_hint", key=7) is None


def test_keyed_accepts_only_a_keyed_unbound_outcome():
    keyer = SessionKeyer("e" * 32)
    session, subject = "v1/" + "S" * 76, "v1/" + "T" * 54
    outcome = route(
        keyer,
        [session],
        [subject],
        {"openai/session": session, "openai/subject": subject},
    )
    kd, log_key = live._keyed(outcome)
    assert kd == outcome.key.kd and log_key == outcome.key.log_key
    assert live._keyed(RouteOutcome(RouteStatus.NO_SESSION)) == "NO_SESSION"
    assert live._keyed(outcome.with_status(RouteStatus.SUSPENDED)) == "SUSPENDED"
    assert live._keyed(object()) == "UNKNOWN"
    forged = SimpleNamespace(
        status=RouteStatus.UNBOUND, key=SimpleNamespace(kd="v1/raw", log_key="x")
    )
    assert live._keyed(forged) == "UNKNOWN"


def test_lab_module_reexports_the_one_extraction():
    assert job_awareness_session.route_call is job_awareness_route.route_call
    assert job_awareness_session.RAW_VALUE is job_awareness_route.RAW_VALUE
    assert job_awareness_session.SESSION_HEADER == "x-openai-session"
