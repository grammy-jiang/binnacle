"""E2 g6 §9.2 S-1 (STRUCT) wire bytes and negatives.

On the c′ shape (closed schema declaring ``job_awareness_hint``, one JSON
mirror text block) the routed STRUCT bytes equal the frozen c′ hinted bytes.
``adapt`` (non-routed), the adapter off, and every forged or foreign receipt
return the original bytes. The META, TEXT, TEXT-U and off golden values of
``test_hint_routed_wire`` / ``test_hint_routed_textu`` run with bindings that
now also name the STRUCT member, so those bytes are unchanged by STRUCT.
"""

import hashlib
import json
from dataclasses import replace
from typing import Any

import pytest
from fastmcp.tools.base import Tool

from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.mcp import job_awareness_hint_identity as identity
from binnacle.mcp.job_awareness_hint import HINT_FIELD, HintAdapter
from binnacle.mcp.job_awareness_hint_identity import Execution
from tests.contracts.job_awareness import e2_cprime as cp
from tests.contracts.job_awareness.e2_composition import NOTE
from tests.contracts.job_awareness.routed_support import (
    RoutedLab,
    routed_app,
    wire_call,
)
from tests.contracts.job_awareness.synthetic_app import in_loop
from tests.contracts.job_awareness.test_hint_schema_support import executed

_JOB = (
    "ja1_55555555555555555555555555555555:666666666666:"
    "g1_77777777777777777777777777777777"
)
_HINT = f"[Binnacle job reminder] {_JOB} unconfirmed"
_LEGACY = "2025-06-18"
_MODERN = "2026-07-28"
_STAMP = (
    '"_meta":{"io.modelcontextprotocol/serverInfo":'
    '{"name":"I2-2 synthetic only","version":"synthetic"}}'
)
_MIRROR = f'{{"text":"{{\\"note\\": \\"{NOTE}\\"}}","type":"text"}}'
_MIRROR_S = (
    f'{{"text":"{{\\"note\\": \\"{NOTE}\\", '
    f'\\"{HINT_FIELD}\\": \\"{_HINT}\\"}}","type":"text"}}'
)
_SC = f'"structuredContent":{{"note":"{NOTE}"}}'
_SC_S = f'"structuredContent":{{"note":"{NOTE}","{HINT_FIELD}":"{_HINT}"}}'
GOLDEN_S = {
    (_LEGACY, "off"): f'{{"content":[{_MIRROR}],"isError":false,{_SC}}}',
    (_LEGACY, "struct"): f'{{"content":[{_MIRROR_S}],"isError":false,{_SC_S}}}',
    (_MODERN, "off"): f'{{"content":[{_MIRROR}],"isError":false,'
    f'"resultType":"complete",{_SC},{_STAMP}}}',
    (_MODERN, "struct"): f'{{"content":[{_MIRROR_S}],"isError":false,'
    f'"resultType":"complete",{_SC_S},{_STAMP}}}',
}
GOLDEN_S_SHA256 = {
    (
        _LEGACY,
        "off",
    ): "bdbc52fd6fa512817b6eec9685767c96c25d79d7c4804ec797c03ca00340bd71",
    (
        _LEGACY,
        "struct",
    ): "76e24ef0fe6efed7f565759ce5c8e20f673a3090ada802474273bec59c898630",
    (
        _MODERN,
        "off",
    ): "e18d25d3f03c36a33606e5671fcbcb51ca71a60e7bde6e850b193e29e2e7d039",
    (
        _MODERN,
        "struct",
    ): "b46d1646680455eec70240b46c53c12d92e1ce81b9502614f0a4a85cc53d2972",
}


def struct(lab: RoutedLab, **options: Any) -> HintAdapter:
    options = dict[str, Any](enabled=True, carrier=HintCarrier.STRUCT) | options
    return lab.routed(schema=cp.CPRIME_SCHEMA, **options)


def untouched(lab: RoutedLab) -> bool:
    return lab.catalog_reads == lab.queries == 0


def test_golden_literals_match_their_digests():
    for key, text in GOLDEN_S.items():
        assert hashlib.sha256(text.encode()).hexdigest() == GOLDEN_S_SHA256[key]  # nosec B101 - pytest assertion


def test_legacy_goldens_equal_the_frozen_cprime_bytes():
    """STRUCT on the c′ shape produces exactly the frozen CV-F (c′) bytes."""
    frozen = cp.frozen()["c_prime"]
    assert frozen["example_hint"] == _HINT  # nosec B101 - pytest assertion
    assert GOLDEN_S[(_LEGACY, "off")] == frozen["wire_legacy"]["unhinted"]  # nosec B101 - pytest assertion
    assert GOLDEN_S[(_LEGACY, "struct")] == frozen["wire_legacy"]["hinted"]  # nosec B101 - pytest assertion


@pytest.mark.parametrize("protocol", [_LEGACY, _MODERN])
@pytest.mark.parametrize("case", ["off", "struct", "adapt", "disabled-binding"])
@in_loop
async def test_struct_wire_bytes(protocol, case):
    """``adapt`` = the non-routed path, which never hints a STRUCT binding."""
    with RoutedLab(1) as lab:
        route = lab.route(lab.job)
        adapter = struct(lab, enabled=case != "off")
        if case == "disabled-binding":
            adapter = replace(adapter, exclusive=False)
        app, outcomes = routed_app(
            adapter,
            cp.cprime_result(NOTE),
            route=None if case == "adapt" else (lambda: route),
            schema=cp.CPRIME_SCHEMA,
        )
        result, raw = await wire_call(app, protocol)
        hinted = case == "struct"
        assert raw.decode() == GOLDEN_S[(protocol, "struct" if hinted else "off")]  # nosec B101 - pytest assertion
        assert (_JOB.encode() in raw) is hinted  # nosec B101 - pytest assertion
        assert result.structured_content.get(HINT_FIELD) == (_HINT if hinted else None)  # nosec B101 - pytest assertion
        if case != "adapt":
            (outcome,) = outcomes
            assert outcome.rendered == ((lab.job,) if hinted else ())  # nosec B101 - pytest assertion


@pytest.mark.parametrize("protocol", [_LEGACY, _MODERN])
@in_loop
async def test_routed_wire_carries_only_rendered_jobs(protocol):
    with RoutedLab(4) as lab:
        routes = iter([lab.route(*lab.jobs[2:]), lab.route(lab.jobs[1])])
        app, outcomes = routed_app(
            struct(lab),
            cp.cprime_result(NOTE),
            route=lambda: next(routes),
            schema=cp.CPRIME_SCHEMA,
        )
        for expected in (lab.jobs[2:], (lab.jobs[1],)):
            _, raw = await wire_call(app, protocol)
            assert outcomes[-1].rendered == expected  # nosec B101 - pytest assertion
            body = json.loads(raw)
            hint = "[Binnacle job reminder] " + "; ".join(
                f"{job.canonical_key} unconfirmed" for job in expected
            )
            assert body["structuredContent"][HINT_FIELD] == hint  # nosec B101 - pytest assertion
            (mirror,) = body["content"]
            assert json.loads(mirror["text"]) == body["structuredContent"]  # nosec B101 - pytest assertion
            for job in set(lab.jobs) - set(expected):
                assert job.canonical_key.encode() not in raw  # nosec B101 - pytest assertion


def test_unchanged_goldens_run_with_struct_aware_bindings():
    """The META/TEXT-U/off goldens use ``RoutedLab.routed``: STRUCT is named."""
    with RoutedLab(1) as lab:
        for adapter in (
            lab.routed(enabled=True, carrier=HintCarrier.META),
            lab.routed(structured=False, enabled=True, carrier=HintCarrier.TEXT),
            lab.routed(enabled=False),
        ):
            assert adapter.bindings.struct is HintCarrier.STRUCT  # nosec B101 - pytest assertion
            assert adapter.struct_bound is False  # nosec B101 - pytest assertion


# -- negatives: producer and receipt ------------------------------------------


@in_loop
async def test_forged_and_foreign_receipts_suppress():
    with RoutedLab(2) as lab:
        adapter = struct(lab)
        twin = Tool(name="synthetic", parameters={}, output_schema=cp.CPRIME_SCHEMA)
        assert twin == adapter.bound_tool and twin is not adapter.bound_tool  # nosec B101 - pytest assertion
        value = cp.cprime_result(NOTE)
        other = cp.cprime_result(NOTE)
        used = executed(value, adapter.bound_tool)
        with identity._LOCK:
            identity._ISSUED.discard(used)  # an already consumed receipt
        receipts = [
            executed(value, twin),
            Execution(adapter.bound_tool, value),
            used,
            executed(other, adapter.bound_tool),
            None,
            adapter.bound_tool,
            "synthetic",
        ]
        for receipt in receipts:
            outcome = await adapter.adapt_routed(
                value, execution=receipt, route=lab.route(*lab.jobs)
            )
            assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion
        assert untouched(lab)  # nosec B101 - pytest assertion
        accepted = await adapter.adapt_routed(
            value,
            execution=executed(value, adapter.bound_tool),
            route=lab.route(*lab.jobs),
        )
        assert (
            accepted.rendered
        )  # the bound object itself is accepted  # nosec B101 - pytest assertion


@pytest.mark.parametrize(
    "change",
    [{"enabled": False}, {"exclusive": False}],
    ids=["disabled", "not-exclusive"],
)
@in_loop
async def test_adapter_off_returns_the_original(change):
    with RoutedLab(1) as lab:
        adapter = replace(struct(lab), **change)
        value = cp.cprime_result(NOTE)
        _, outcome = await lab.call(adapter, lab.route(lab.job), value)
        assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion
        assert untouched(lab) and adapter.last_meter is None  # nosec B101 - pytest assertion


@in_loop
async def test_identity_mutation_after_bind_suppresses():
    with RoutedLab(1) as lab:
        for name, value in (("name", "renamed"), ("version", "2")):
            adapter = struct(lab)
            object.__setattr__(adapter.bound_tool, name, value)
            result = cp.cprime_result(NOTE)
            _, outcome = await lab.call(adapter, lab.route(lab.job), result)
            assert outcome.result is result and outcome.rendered == ()  # nosec B101 - pytest assertion
        assert untouched(lab)  # nosec B101 - pytest assertion
