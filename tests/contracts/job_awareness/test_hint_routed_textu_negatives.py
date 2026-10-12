"""E2 g6 §9.2 G-U1..G-U5: routed TEXT-U negatives (D0, before the D1 review).

Every case here must return the original result object (so the original
bytes), name no rendered job, read no observation or receipt state, and, on
the real lab ledger, leave every job ``PENDING``.
"""

from dataclasses import replace

import pytest
from fastmcp.tools.base import Tool, ToolResult

from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.features.commands.job_awareness.session_emission import emit_hint
from binnacle.mcp import job_awareness_hint_identity as identity
from binnacle.mcp.job_awareness_hint import NO_STRUCTURE, HintAdapter
from binnacle.mcp.job_awareness_hint_identity import Execution, producer_identity
from tests.contracts.job_awareness.e2_composition import E2Server, chat
from tests.contracts.job_awareness.e2_scoring import ledger_rows
from tests.contracts.job_awareness.routed_support import RoutedLab, text_only
from tests.contracts.job_awareness.synthetic_app import in_loop
from tests.contracts.job_awareness.test_hint_schema_support import executed


def text_u(lab: RoutedLab, **options: object) -> HintAdapter:
    options = {"enabled": True, "carrier": HintCarrier.TEXT} | options
    return lab.routed(structured=False, **options)


async def routed(adapter, lab, value, receipt):
    return await adapter.adapt_routed(
        value, execution=receipt, route=lab.route(*lab.jobs)
    )


def untouched(lab: RoutedLab) -> bool:
    return lab.catalog_reads == lab.queries == 0


def issued(receipt: object) -> bool:
    with identity._LOCK:
        return receipt in identity._ISSUED


# -- G-U1: a value-equal second schema-less Tool is a different producer -------


@in_loop
async def test_gu1_value_equal_second_tool_is_suppressed():
    with RoutedLab(2) as lab:
        adapter = text_u(lab)
        twin = Tool(name="synthetic", parameters={}, output_schema=None)
        assert twin == adapter.bound_tool and twin is not adapter.bound_tool  # nosec B101 - pytest assertion
        assert producer_identity(twin, unstructured=True) == adapter.identity  # nosec B101 - pytest assertion
        value = text_only()
        outcome = await routed(adapter, lab, value, executed(value, twin))
        assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion
        assert untouched(lab)  # nosec B101 - pytest assertion
        # The bound object itself is accepted: the twin was the only fault.
        value = text_only()
        good = await routed(adapter, lab, value, executed(value, adapter.bound_tool))
        assert good.result is not value and good.rendered  # nosec B101 - pytest assertion


# -- G-U2: forged, reused, other-result, None and non-Execution receipts --------


@in_loop
async def test_gu2_forged_and_foreign_receipts_are_suppressed():
    with RoutedLab(2) as lab:
        adapter = text_u(lab)
        value = text_only()
        other = text_only()
        kept = executed(
            other, adapter.bound_tool
        )  # an issued receipt for another result
        forged = Execution(adapter.bound_tool, value)  # hand-built, never issued
        for receipt in (forged, kept, None, adapter.bound_tool, "synthetic", object()):
            outcome = await routed(adapter, lab, value, receipt)
            assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion
        assert untouched(lab)  # nosec B101 - pytest assertion
        assert issued(kept)  # nosec B101 - pytest assertion - the other-result receipt was not consumed
        assert not issued(forged)  # nosec B101 - pytest assertion
        first = await routed(adapter, lab, other, kept)
        assert first.result is not other and first.rendered  # nosec B101 - pytest assertion
        assert not issued(kept)  # nosec B101 - pytest assertion
        reads = lab.catalog_reads
        reused = await routed(adapter, lab, other, kept)
        assert reused.result is other and reused.rendered == ()  # nosec B101 - pytest assertion
        assert lab.catalog_reads == reads  # nosec B101 - pytest assertion


@pytest.mark.parametrize("receipt", ["forged", "none", "other", "tool"])
@in_loop
async def test_gu2_bad_receipts_reserve_and_emit_nothing_on_the_ledger(
    tmp_path, receipt
):
    server = E2Server(tmp_path / "phase", carrier=HintCarrier.TEXT, structured=False)
    who = chat("gu2")
    handle = await server.lab.start_fixture(server.outcome(who), "R3-SYN-JOB-01")
    await server.seal(who, str(handle))
    value = text_only()
    execution = {
        "forged": Execution(server.tool, value),
        "none": None,
        "other": executed(text_only(), server.tool),
        "tool": server.tool,
    }[receipt]
    result = await emit_hint(
        server.lab,
        server.outcome(who),
        value,
        execution=execution,
        adapter=server.adapter,
    )
    await server.workers.close()
    assert result is value  # nosec B101 - pytest assertion
    states = {str(s) for (s,) in ledger_rows(server, "SELECT state FROM emit")}
    assert states == {"PENDING"}  # nosec B101 - pytest assertion


# -- G-U3: identity mutation after bind; a subclass is unknown ----------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [("name", "synthetic2"), ("version", "2"), ("version", None)],
)
@in_loop
async def test_gu3_name_or_version_change_after_bind_is_suppressed(field, value):
    with RoutedLab(1) as lab:
        adapter = text_u(lab)
        if value is None:  # bind with a version, then drop it
            adapter = replace(
                adapter,
                tool=Tool(
                    name="synthetic", version="1", parameters={}, output_schema=None
                ),
            )
        object.__setattr__(adapter.bound_tool, field, value)
        result = text_only()
        outcome = await routed(
            adapter, lab, result, executed(result, adapter.bound_tool)
        )
        assert outcome.result is result and outcome.rendered == ()  # nosec B101 - pytest assertion
        assert untouched(lab)  # nosec B101 - pytest assertion


class SubTool(Tool):
    """A subclass: never a reviewed native producer."""


@in_loop
async def test_gu3_subclass_is_unknown():
    sub = SubTool(name="synthetic", parameters={}, output_schema=None)
    assert producer_identity(sub, unstructured=True) is None  # nosec B101 - pytest assertion
    with RoutedLab(1) as lab:
        with pytest.raises(ValueError, match="native tool"):
            replace(text_u(lab), tool=sub)
        adapter = text_u(lab)
        value = text_only()
        outcome = await routed(adapter, lab, value, executed(value, sub))
        assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion
        assert untouched(lab)  # nosec B101 - pytest assertion


# -- G-U4: adapter off ------------------------------------------------------------


@pytest.mark.parametrize(
    "options",
    [{"enabled": False}, {"exclusive": False}, {"enabled": False, "exclusive": False}],
    ids=["disabled", "not-exclusive", "both"],
)
@in_loop
async def test_gu4_adapter_off_returns_the_original(options):
    with RoutedLab(2) as lab:
        adapter = text_u(lab, **options)
        assert adapter.schema is NO_STRUCTURE  # nosec B101 - pytest assertion
        value = text_only()
        receipt = executed(value, adapter.bound_tool)
        outcome = await routed(adapter, lab, value, receipt)
        assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion
        assert await adapter.adapt(value, execution=receipt) is value  # nosec B101 - pytest assertion
        assert untouched(lab) and adapter.last_meter is None  # nosec B101 - pytest assertion
        assert issued(receipt)  # nosec B101 - pytest assertion - gate fails before the receipt is claimed


@pytest.mark.parametrize("off", ["enabled", "exclusive"])
@in_loop
async def test_gu4_adapter_off_keeps_jobs_pending_on_the_ledger(tmp_path, off):
    server = E2Server(tmp_path / "phase", carrier=HintCarrier.TEXT, structured=False)
    adapter = replace(
        server.build_adapter(enabled=off != "enabled"), exclusive=off != "exclusive"
    )
    who = chat("gu4")
    handle = await server.lab.start_fixture(server.outcome(who), "R3-SYN-JOB-01")
    await server.seal(who, str(handle))
    value = text_only()
    result = await emit_hint(
        server.lab,
        server.outcome(who),
        value,
        execution=executed(value, server.tool),
        adapter=adapter,
    )
    await server.workers.close()
    assert result is value  # nosec B101 - pytest assertion
    states = {str(s) for (s,) in ledger_rows(server, "SELECT state FROM emit")}
    assert states == {"PENDING"}  # nosec B101 - pytest assertion


# -- G-U5: non-routed bindings with a schema-less tool are inert -----------------


def mixed(adapter: HintAdapter, tool: Tool) -> HintAdapter:
    """The same bindings without route types, bound to a schema-less tool."""
    bindings = replace(adapter.bindings, route_type=None, candidate_type=None)
    return replace(adapter, bindings=bindings, tool=tool)


@pytest.mark.parametrize("carrier", [HintCarrier.TEXT, HintCarrier.META])
@in_loop
async def test_gu5_mixed_binding_is_inert_on_both_paths(carrier):
    with RoutedLab(2) as lab:
        tool = Tool(name="synthetic", parameters={}, output_schema=None)
        adapter = mixed(lab.routed(enabled=True, carrier=HintCarrier.META), tool)
        adapter.carrier = carrier
        assert adapter.schema is None and adapter.identity is None  # nosec B101 - pytest assertion
        value = text_only()
        receipt = executed(value, adapter.bound_tool)
        assert await adapter.adapt(value, execution=receipt) is value  # nosec B101 - pytest assertion
        outcome = await routed(adapter, lab, value, receipt)
        assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion
        assert untouched(lab) and issued(receipt)  # nosec B101 - pytest assertion


@in_loop
async def test_gu5_mixed_binding_reserves_nothing_on_the_ledger(tmp_path):
    server = E2Server(tmp_path / "phase", carrier=HintCarrier.TEXT, structured=False)
    adapter = mixed(server.adapter, server.tool)
    who = chat("gu5")
    handle = await server.lab.start_fixture(server.outcome(who), "R3-SYN-JOB-01")
    await server.seal(who, str(handle))
    value: ToolResult = text_only()
    result = await emit_hint(
        server.lab,
        server.outcome(who),
        value,
        execution=executed(value, server.tool),
        adapter=adapter,
    )
    await server.workers.close()
    assert result is value  # nosec B101 - pytest assertion
    states = {str(s) for (s,) in ledger_rows(server, "SELECT state FROM emit")}
    assert states == {"PENDING"}  # nosec B101 - pytest assertion
