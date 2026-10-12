"""Review TEXTU-G2-01: a carrier changed while a routed render is in flight.

A barrier pauses the worker inside ``binding.check`` (after the render entry
check). The test then changes ``adapter.carrier`` through the trusted-code bypass
``object.__setattr__`` (plain assignment raises: routed adapters are
immutable, see ``test_hint_routed_immutable``) and releases the worker.
These tests keep the per-call checks honest as defence in depth.
The render pins the bind-approved carrier for the whole call and checks for
drift again before it returns, so the hint is suppressed: the original
object and bytes, ``rendered == ()``, and on the real lab ledger the
reservation is reset to ``PENDING``. A drift after the adapter returned is
caught by the emission before its EMITTED commit (the job is ``ABORTED``).
"""

import asyncio
from dataclasses import replace
from threading import Event

import pytest

from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.features.commands.job_awareness.session_emission import emit_hint
from tests.contracts.job_awareness.e2_composition import E2Server, chat, running
from tests.contracts.job_awareness.e2_scoring import ledger_rows
from tests.contracts.job_awareness.routed_support import RoutedLab, text_only
from tests.contracts.job_awareness.synthetic_app import in_loop, original
from tests.contracts.job_awareness.test_e2_wire_handoff import PLAIN, PLAIN_U
from tests.contracts.job_awareness.test_hint_routed_emission import note
from tests.contracts.job_awareness.test_hint_schema_support import executed

META, TEXT = HintCarrier.META, HintCarrier.TEXT
DRIFT = [(META, TEXT, True), (TEXT, META, False)]
IDS = ["schema-META-to-TEXT", "TEXT-U-to-META"]
WAIT_S = 10


class Barrier:
    """Pause the first ``check`` call of the worker until released."""

    def __init__(self, check):
        self.check, self.entered, self.release = check, Event(), Event()
        self.calls = 0

    def __call__(self, grant, job, scopes):
        self.calls += 1
        if self.calls == 1:
            self.entered.set()
            if not self.release.wait(WAIT_S):
                raise TimeoutError("barrier not released")
        return self.check(grant, job, scopes)


def force(adapter, name: str, value: object) -> None:
    """Trusted in-process bypass of the routed immutability (out of model)."""
    object.__setattr__(adapter, name, value)


def pause(adapter):
    """A new adapter (routed adapters are immutable) whose check pauses."""
    barrier = Barrier(adapter.bindings.check)
    return replace(adapter, bindings=replace(adapter.bindings, check=barrier)), barrier


async def drift_during(barrier: Barrier, adapter, drift, call):
    """Run ``call``; change the carrier while the worker is paused in check."""
    task = asyncio.ensure_future(call)
    assert await asyncio.to_thread(barrier.entered.wait, WAIT_S)  # nosec B101 - pytest assertion
    force(adapter, "carrier", drift)
    barrier.release.set()
    return await task


def states(server: E2Server) -> set[str]:
    return {str(s) for (s,) in ledger_rows(server, "SELECT state FROM emit")}


@pytest.mark.parametrize(("carrier", "drift", "structured"), DRIFT, ids=IDS)
@in_loop
async def test_drift_inside_the_render_suppresses(carrier, drift, structured):
    with RoutedLab(1) as lab:
        adapter = lab.routed(structured=structured, enabled=True, carrier=carrier)
        adapter, barrier = pause(adapter)
        value = original() if structured else text_only()
        receipt = executed(value, adapter.bound_tool)
        call = adapter.adapt_routed(value, execution=receipt, route=lab.route(lab.job))
        outcome = await drift_during(barrier, adapter, drift, call)
        assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion
        assert adapter.routed_carrier is carrier and barrier.calls == 1  # nosec B101 - pytest assertion
        assert len(value.content) == 1 and value.meta == {"existing": "kept"}  # nosec B101 - pytest assertion


@pytest.mark.parametrize(("carrier", "drift", "structured"), DRIFT, ids=IDS)
@in_loop
async def test_drift_inside_the_render_on_the_wire_resets_the_job(
    tmp_path, carrier, drift, structured
):
    server = E2Server(tmp_path / "phase", carrier=carrier, structured=structured)
    who = chat("race")
    plain = PLAIN if structured else PLAIN_U
    async with running(server) as wire:
        start = await wire.call(who, "fixture_start", {"slot": "R3-SYN-JOB-01"})
        await server.seal(who, str(start.data["job"]))
        server.adapter, barrier = pause(server.adapter)
        call = wire.call(who, "fixture_unrelated_read")
        raced = await drift_during(barrier, server.adapter, drift, call)
        after = states(server)
        force(server.adapter, "carrier", carrier)
        restored = await wire.call(who, "fixture_unrelated_read")
    assert raced.raw.decode() == plain and raced.row["ja_hint"] == "0"  # nosec B101 - pytest assertion
    assert after == {"PENDING"}  # nosec B101 - pytest assertion
    assert restored.hints and states(server) == {"EMITTED"}  # nosec B101 - pytest assertion


@pytest.mark.parametrize("point", ["after_adapt", "after_validation", "before_commit"])
@pytest.mark.parametrize(("carrier", "drift", "structured"), DRIFT, ids=IDS)
@in_loop
async def test_drift_before_the_commit_never_emits(
    tmp_path, carrier, drift, structured, point
):
    server = E2Server(tmp_path / "phase", carrier=carrier, structured=structured)
    who = chat("commit")
    handle = await server.lab.start_fixture(server.outcome(who), "R3-SYN-JOB-01")
    await server.seal(who, str(handle))

    async def checkpoint(name: str) -> None:
        if name == point:
            force(server.adapter, "carrier", drift)

    value = note(structured)
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
