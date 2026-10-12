"""TEXTU-G2-01 for STRUCT (g6 §9.2 S-1): drift while a routed render runs.

Mirrors ``test_hint_routed_carrier_race``. A barrier pauses the worker
inside ``binding.check`` (after the render entry check). The test then
changes the carrier or the STRUCT snapshot through the trusted-code bypass
``object.__setattr__`` (plain assignment raises: routed adapters are
immutable, see ``test_hint_routed_struct_immutable``) and releases the
worker. These tests keep the per-call checks honest as defence in depth. The
render pinned the bind-approved carrier, the STRUCT snapshot and the schema
at entry and checks for drift again before it returns, so the hint is
suppressed: the original object and bytes, ``rendered == ()``, and on the
real lab ledger the reservation is reset to ``PENDING``. A drift after the
adapter returned is caught before the EMITTED commit (the job is
``ABORTED``).
"""

import asyncio

import pytest

from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.features.commands.job_awareness.session_emission import emit_hint
from binnacle.mcp.job_awareness_hint import HINT_FIELD
from tests.contracts.job_awareness import e2_cprime as cp
from tests.contracts.job_awareness.e2_composition import NOTE, chat, running
from tests.contracts.job_awareness.routed_support import RoutedLab
from tests.contracts.job_awareness.synthetic_app import in_loop
from tests.contracts.job_awareness.test_hint_routed_carrier_race import (
    WAIT_S,
    pause,
    states,
)
from tests.contracts.job_awareness.test_hint_routed_struct_drift import bypass
from tests.contracts.job_awareness.test_hint_schema_support import executed

META, TEXT, STRUCT = HintCarrier.META, HintCarrier.TEXT, HintCarrier.STRUCT
DRIFT = [(STRUCT, META), (STRUCT, TEXT), (META, STRUCT)]
IDS = ["STRUCT-to-META", "STRUCT-to-TEXT", "META-to-STRUCT"]
UNHINTED = cp.frozen()["c_prime"]["wire_legacy"]["unhinted"]


async def drift_during(barrier, adapter, drift, call):
    """Run ``call``; while the worker is paused in check, a plain carrier
    assignment raises, then the trusted bypass changes it."""
    task = asyncio.ensure_future(call)
    assert await asyncio.to_thread(barrier.entered.wait, WAIT_S)  # nosec B101 - pytest assertion
    bypass(adapter, "carrier", drift)
    barrier.release.set()
    return await task


def bound(lab: RoutedLab, carrier: HintCarrier):
    return lab.routed(schema=cp.CPRIME_SCHEMA, enabled=True, carrier=carrier)


@pytest.mark.parametrize(("carrier", "drift"), DRIFT, ids=IDS)
@in_loop
async def test_drift_inside_the_render_suppresses(carrier, drift):
    with RoutedLab(1) as lab:
        adapter = bound(lab, carrier)
        adapter, barrier = pause(adapter)
        value = cp.cprime_result(NOTE)
        receipt = executed(value, adapter.bound_tool)
        call = adapter.adapt_routed(value, execution=receipt, route=lab.route(lab.job))
        outcome = await drift_during(barrier, adapter, drift, call)
        assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion
        assert adapter.routed_carrier is carrier and barrier.calls == 1  # nosec B101 - pytest assertion
        assert value.structured_content == {"note": NOTE}  # nosec B101 - pytest assertion
        assert value.meta is None and len(value.content) == 1  # nosec B101 - pytest assertion


@pytest.mark.parametrize(
    "flip", [False, True], ids=["snapshot-cleared", "snapshot-set"]
)
@in_loop
async def test_struct_snapshot_changed_inside_the_render_suppresses(flip):
    """``struct_bound`` is pinned at entry and re-checked before return."""
    with RoutedLab(1) as lab:
        adapter = bound(lab, META if flip else STRUCT)
        adapter, barrier = pause(adapter)
        value = cp.cprime_result(NOTE)
        receipt = executed(value, adapter.bound_tool)
        call = adapter.adapt_routed(value, execution=receipt, route=lab.route(lab.job))
        task = asyncio.ensure_future(call)
        assert await asyncio.to_thread(barrier.entered.wait, WAIT_S)  # nosec B101 - pytest assertion
        bypass(adapter, "struct_bound", flip)
        barrier.release.set()
        outcome = await task
        assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion


@pytest.mark.parametrize("drift", [META, TEXT])
@in_loop
async def test_drift_inside_the_render_on_the_wire_resets_the_job(tmp_path, drift):
    server = cp.v2s_server(tmp_path / "phase")
    who = chat("race-S")
    async with running(server) as wire:
        start = await wire.call(who, "fixture_start", {"slot": "R3-SYN-JOB-01"})
        await server.seal(who, str(start.data["job"]))
        server.adapter, barrier = pause(server.adapter)
        call = wire.call(who, "fixture_unrelated_read")
        raced = await drift_during(barrier, server.adapter, drift, call)
        after = states(server)
        bypass(server.adapter, "carrier", STRUCT)
        restored = await wire.call(who, "fixture_unrelated_read")
    assert raced.raw.decode() == UNHINTED and raced.row["ja_hint"] == "0"  # nosec B101 - pytest assertion
    assert after == {"PENDING"}  # nosec B101 - pytest assertion
    assert HINT_FIELD in restored.result["structuredContent"]  # nosec B101 - pytest assertion
    assert restored.hints and states(server) == {"EMITTED"}  # nosec B101 - pytest assertion


@pytest.mark.parametrize("point", ["after_adapt", "after_validation", "before_commit"])
@pytest.mark.parametrize("drift", [META, TEXT, "snapshot"])
@in_loop
async def test_drift_before_the_commit_never_emits(tmp_path, drift, point):
    server = cp.v2s_server(tmp_path / "phase")
    who = chat("commit-S")
    handle = await server.lab.start_fixture(server.outcome(who), "R3-SYN-JOB-01")
    await server.seal(who, str(handle))

    async def checkpoint(name: str) -> None:
        if name != point:
            return
        if drift == "snapshot":
            bypass(server.adapter, "struct_bound", False)
        else:
            bypass(server.adapter, "carrier", drift)

    value = cp.cprime_result(NOTE)
    result = await emit_hint(
        server.lab,
        server.outcome(who),
        value,
        execution=executed(value, server.tool),
        adapter=server.adapter,
        checkpoint=checkpoint,
    )
    await server.workers.close()
    assert result is value  # nosec B101 - pytest assertion
    assert states(server) == {"ABORTED"}  # nosec B101 - pytest assertion


@in_loop
async def test_without_drift_the_same_paths_emit(tmp_path):
    """Control: the barrier and checkpoints alone do not suppress."""
    server = cp.v2s_server(tmp_path / "phase")
    who = chat("control-S")
    handle = await server.lab.start_fixture(server.outcome(who), "R3-SYN-JOB-01")
    await server.seal(who, str(handle))
    value = cp.cprime_result(NOTE)
    result = await emit_hint(
        server.lab,
        server.outcome(who),
        value,
        execution=executed(value, server.tool),
        adapter=server.adapter,
    )
    await server.workers.close()
    assert result is not value and HINT_FIELD in result.structured_content  # nosec B101 - pytest assertion
    assert states(server) == {"EMITTED"}  # nosec B101 - pytest assertion
