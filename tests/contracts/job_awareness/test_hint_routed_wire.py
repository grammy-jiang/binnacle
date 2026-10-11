"""CA-2 wire bytes: ``adapt`` is byte-identical to master; routed bytes carry
the hint only for the rendered jobs.

The golden result bytes below were captured from master 32cbe56 (before CA-2)
with the same harness: native FastMCP streamable HTTP, stateless JSON
responses, the I2-2 synthetic lab job and both protocol eras.
"""

import json
from dataclasses import replace

import pytest

from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.mcp.job_awareness_hint import META_KEY, HintAdapter
from tests.contracts.job_awareness.routed_support import (
    RoutedLab,
    routed_app,
    wire_call,
)
from tests.contracts.job_awareness.synthetic_app import in_loop, original

_JOB = (
    "ja1_55555555555555555555555555555555:666666666666:"
    "g1_77777777777777777777777777777777"
)
_HINT = f"[Binnacle job reminder] {_JOB} unconfirmed"
_STAMP = (
    '"io.modelcontextprotocol/serverInfo":'
    '{"name":"I2-2 synthetic only","version":"synthetic"}'
)
_TEXT = '{"text":"Synthetic result","type":"text"}'
_HINT_TEXT = f'{{"text":"{_HINT}","type":"text"}}'
_OK = '"structuredContent":{"ok":true}'
_LEGACY = "2025-06-18"
_MODERN = "2026-07-28"
GOLDEN = {
    (_LEGACY, "off"): f'{{"_meta":{{"existing":"kept"}},"content":[{_TEXT}],'
    f'"isError":false,{_OK}}}',
    (_LEGACY, "error"): f'{{"_meta":{{"existing":"kept"}},"content":[{_TEXT}],'
    f'"isError":true,{_OK}}}',
    (_LEGACY, "meta"): f'{{"_meta":{{"existing":"kept","{META_KEY}":"{_HINT}"}},'
    f'"content":[{_TEXT}],"isError":false,{_OK}}}',
    (_LEGACY, "text"): f'{{"_meta":{{"existing":"kept"}},"content":[{_TEXT},'
    f'{_HINT_TEXT}],"isError":false,{_OK}}}',
    (_MODERN, "off"): f'{{"_meta":{{"existing":"kept",{_STAMP}}},'
    f'"content":[{_TEXT}],"isError":false,"resultType":"complete",{_OK}}}',
    (_MODERN, "error"): f'{{"_meta":{{"existing":"kept",{_STAMP}}},'
    f'"content":[{_TEXT}],"isError":true,"resultType":"complete",{_OK}}}',
    (_MODERN, "meta"): f'{{"_meta":{{"existing":"kept","{META_KEY}":"{_HINT}",'
    f'{_STAMP}}},"content":[{_TEXT}],"isError":false,"resultType":"complete",'
    f"{_OK}}}",
    (_MODERN, "text"): f'{{"_meta":{{"existing":"kept",{_STAMP}}},'
    f'"content":[{_TEXT},{_HINT_TEXT}],"isError":false,"resultType":"complete",'
    f"{_OK}}}",
}
#: sha256 of the master bytes, kept beside the literals as a second witness.
GOLDEN_SHA256 = {
    (
        _LEGACY,
        "off",
    ): "c1fbe54e499618a9148453cf86e152757fa30b460be8d5981242876d4bdab8ad",
    (
        _LEGACY,
        "error",
    ): "4065a7f3bb07e93e90a0aede707dcaadd845a0ba2693655afbba9398b113867b",
    (
        _LEGACY,
        "meta",
    ): "79d9dc085200254d9cfbba7988b12d2a3475ab7f089961229b75a859b0434090",
    (
        _LEGACY,
        "text",
    ): "b98a4829e4aa174cb9c00f1fec496ae8b401442ca5854a3b804f7faafba69362",
    (
        _MODERN,
        "off",
    ): "07904b1cf5153def2bc3dab64328d108de00378f54c7aaecb092e1af33e6922d",
    (
        _MODERN,
        "error",
    ): "318b608009320fce56c2161849a7c1d99534341f860a2e417d4e059989a9d17a",
    (
        _MODERN,
        "meta",
    ): "763d97b78ca313e3d327f53eb35138a5d6234e16232d3d50859d4f06a2137046",
    (
        _MODERN,
        "text",
    ): "587f26b7b4b16a21dec4c62a805b34548ada097aaf94c95e46fd38e3e12dea8e",
}
CASES = [(p, c) for p in (_LEGACY, _MODERN) for c in ("off", "error", "meta", "text")]


def case_value(case):
    value = original()
    if case == "error":
        value.is_error = True
    return value


def plain(lab, case) -> HintAdapter:
    carrier = HintCarrier.TEXT if case == "text" else HintCarrier.META
    return lab.adapter(enabled=case != "off", carrier=carrier)


def test_golden_literals_match_their_digests():
    import hashlib

    for key, text in GOLDEN.items():
        assert hashlib.sha256(text.encode()).hexdigest() == GOLDEN_SHA256[key]  # nosec B101 - pytest assertion


@pytest.mark.parametrize(("protocol", "case"), CASES)
@in_loop
async def test_adapt_wire_bytes_equal_master(protocol, case):
    with RoutedLab(1) as lab:
        app, outcomes = routed_app(plain(lab, case), case_value(case))
        _, raw = await wire_call(app, protocol)
        assert raw.decode() == GOLDEN[(protocol, case)]  # nosec B101 - pytest assertion
        assert len(outcomes) == 1  # nosec B101 - pytest assertion


@pytest.mark.parametrize(("protocol", "case"), CASES)
@in_loop
async def test_routed_wire_bytes_equal_adapt_for_the_same_job(protocol, case):
    """Same single job via a route: identical bytes; rendered iff hinted."""
    with RoutedLab(1) as lab:
        carrier = HintCarrier.TEXT if case == "text" else HintCarrier.META
        adapter = lab.routed(enabled=case != "off", carrier=carrier)
        route = lab.route(lab.job)
        app, outcomes = routed_app(adapter, case_value(case), route=lambda: route)
        _, raw = await wire_call(app, protocol)
        assert raw.decode() == GOLDEN[(protocol, case)]  # nosec B101 - pytest assertion
        (outcome,) = outcomes
        hinted = case in ("meta", "text")
        assert outcome.rendered == ((lab.job,) if hinted else ())  # nosec B101 - pytest assertion
        assert (_JOB in raw.decode()) is hinted  # nosec B101 - pytest assertion


@pytest.mark.parametrize("protocol", [_LEGACY, _MODERN])
@in_loop
async def test_routed_wire_carries_only_rendered_jobs(protocol):
    with RoutedLab(4) as lab:
        adapter = lab.routed(enabled=True, carrier=HintCarrier.TEXT)
        routes = iter([lab.route(*lab.jobs[2:]), lab.route(lab.jobs[1])])
        app, outcomes = routed_app(adapter, route=lambda: next(routes))
        for expected in (lab.jobs[2:], (lab.jobs[1],)):
            result, raw = await wire_call(app, protocol)
            outcome = outcomes[-1]
            assert outcome.rendered == expected  # nosec B101 - pytest assertion
            text = json.loads(raw)["content"][-1]["text"]
            assert text == "[Binnacle job reminder] " + "; ".join(  # nosec B101 - pytest assertion
                f"{job.canonical_key} unconfirmed" for job in expected
            )
            for job in set(lab.jobs) - set(expected):
                assert job.canonical_key.encode() not in raw  # nosec B101 - pytest assertion
            assert result.content[-1].text == text  # nosec B101 - pytest assertion


@in_loop
async def test_routed_off_and_suppressed_wire_bytes_are_the_original():
    with RoutedLab(2) as lab:
        route = lab.route(*lab.jobs)
        for adapter in (
            lab.routed(enabled=False),
            replace(
                lab.routed(enabled=True),
                bindings=replace(lab.routed().bindings, render=lambda *args: None),
            ),
        ):
            app, outcomes = routed_app(adapter, route=lambda: route)
            _, raw = await wire_call(app, _LEGACY)
            assert raw.decode() == GOLDEN[(_LEGACY, "off")]  # nosec B101 - pytest assertion
            assert outcomes[-1].rendered == ()  # nosec B101 - pytest assertion
