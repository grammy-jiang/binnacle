"""TEXTU-G3/G4 for STRUCT (g6 §9.2 S-1): the routed STRUCT adapter is immutable.

The STRUCT binding (``struct_bound``, the STRUCT ``routed_carrier``, the
bindings' ``struct`` member and the bound schema) is part of the same
immutable routed configuration: assigning or deleting any field except
``last_meter`` raises. In-flight changes inside the render and inside the
final EMITTED commit cannot be made on the v2-S lab tool, and an arm switch
is a new adapter: the E2 Router captures the adapter at dispatch, so a call
in flight keeps its arm and the next call uses the new one.
"""

import asyncio
import dataclasses
from dataclasses import replace
from threading import Event

import pytest

from binnacle.features.commands.job_awareness import session_emission
from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.features.commands.job_awareness.session_emission import emit_hint
from binnacle.mcp.job_awareness_hint import HINT_FIELD, HintAdapter
from tests.contracts.job_awareness import e2_cprime as cp
from tests.contracts.job_awareness.e2_composition import NOTE, chat, running
from tests.contracts.job_awareness.e2_scoring import ledger_rows
from tests.contracts.job_awareness.routed_support import RoutedLab
from tests.contracts.job_awareness.synthetic_app import in_loop
from tests.contracts.job_awareness.test_hint_routed_immutable import (
    WAIT_S,
    Pause,
    attempts,
)
from tests.contracts.job_awareness.test_hint_schema_support import executed

FIELDS = [f.name for f in dataclasses.fields(HintAdapter) if f.name != "last_meter"]
STRUCT_CHANGES = {"struct_bound": False, "routed_carrier": HintCarrier.META}


def struct_attempts(adapter) -> list[str]:
    """``attempts`` plus the STRUCT snapshot; the names that did NOT raise."""
    allowed = attempts(adapter)
    for name, value in STRUCT_CHANGES.items():
        try:
            setattr(adapter, name, value)
        except AttributeError:
            continue
        allowed.append(name)
    return allowed


def emit_states(server) -> set[str]:
    return {str(s) for (s,) in ledger_rows(server, "SELECT state FROM emit")}


def test_every_routed_struct_field_is_immutable():
    assert "struct_bound" in FIELDS and "routed_carrier" in FIELDS  # nosec B101 - pytest assertion
    with RoutedLab(1) as lab:
        adapter = lab.routed(
            schema=cp.CPRIME_SCHEMA, enabled=True, carrier=HintCarrier.STRUCT
        )
        assert adapter.struct_bound is True  # nosec B101 - pytest assertion
        before = dict(vars(adapter))
        for name in FIELDS:
            with pytest.raises(AttributeError, match="immutable"):
                setattr(adapter, name, getattr(adapter, name))
            with pytest.raises(AttributeError, match="immutable"):
                delattr(adapter, name)
        with pytest.raises(AttributeError, match="immutable"):
            adapter.bind_server(object())
        assert struct_attempts(adapter) == []  # nosec B101 - pytest assertion
        assert vars(adapter) == before  # nosec B101 - pytest assertion
        other = replace(adapter, enabled=False)  # a new arm is a new adapter
        assert other is not adapter and adapter.enabled is True  # nosec B101 - pytest assertion
        assert other.struct_bound is True and other.enabled is False  # nosec B101 - pytest assertion
        assert other.routed_carrier is HintCarrier.STRUCT  # nosec B101 - pytest assertion


def test_v2s_arms_are_immutable_adapters(tmp_path):
    server = cp.v2s_server(tmp_path / "phase")
    for adapter in (server.adapter, server.build_adapter(enabled=False)):
        assert adapter.struct_bound is True  # nosec B101 - pytest assertion
        assert struct_attempts(adapter) == []  # nosec B101 - pytest assertion


@in_loop
async def test_in_flight_changes_inside_the_render_cannot_be_made(tmp_path):
    server = cp.v2s_server(tmp_path / "phase")
    pause = Pause(server.adapter.bindings.check)
    server.adapter = replace(
        server.adapter, bindings=replace(server.adapter.bindings, check=pause)
    )
    pause.adapter = server.adapter
    seen: list[str] = []
    real = pause.check

    def check(grant, job, scopes):
        if not seen:
            seen.extend(struct_attempts(server.adapter) or ["none"])
        return real(grant, job, scopes)

    pause.check = check
    who = chat("inflight-S")
    async with running(server) as wire:
        start = await wire.call(who, "fixture_start", {"slot": "R3-SYN-JOB-01"})
        await server.seal(who, str(start.data["job"]))
        call = await wire.call(who, "fixture_unrelated_read")
    assert pause.allowed == [] and seen == ["none"]  # nosec B101 - pytest assertion
    assert call.hints and HINT_FIELD in call.result["structuredContent"]  # nosec B101 - pytest assertion
    assert "_meta" not in call.result and len(call.result["content"]) == 1  # nosec B101 - pytest assertion
    assert emit_states(server) == {"EMITTED"}  # nosec B101 - pytest assertion


@in_loop
async def test_in_flight_changes_inside_the_final_commit_cannot_be_made(
    tmp_path, monkeypatch
):
    server = cp.v2s_server(tmp_path / "phase")
    who = chat("late-S")
    handle = await server.lab.start_fixture(server.outcome(who), "R3-SYN-JOB-01")
    await server.seal(who, str(handle))
    real, seen = session_emission._valid, []

    def valid(*args, **kwargs):
        seen.append(struct_attempts(server.adapter) if len(seen) == 1 else [])
        return real(*args, **kwargs)

    monkeypatch.setattr(session_emission, "_valid", valid)
    value = cp.cprime_result(NOTE)
    result = await emit_hint(
        server.lab,
        server.outcome(who),
        value,
        execution=executed(value, server.tool),
        adapter=server.adapter,
    )
    await server.workers.close()
    assert len(seen) == 2 and seen == [[], []]  # nosec B101 - pytest assertion
    assert result is not value and HINT_FIELD in result.structured_content  # nosec B101 - pytest assertion
    assert emit_states(server) == {"EMITTED"}  # nosec B101 - pytest assertion


@in_loop
async def test_v2s_arm_switch_keeps_the_dispatched_adapter(tmp_path):
    """The Router captures the adapter at dispatch: a switch to the control
    arm while a candidate call is in flight affects only later calls."""
    server = cp.v2s_server(tmp_path / "phase")
    candidate = server.build_adapter(enabled=True)
    control = server.build_adapter(enabled=False)
    paused, release = Event(), Event()
    check = candidate.bindings.check

    def slow(grant, job, scopes):
        paused.set()
        release.wait(WAIT_S)
        return check(grant, job, scopes)

    server.adapter = replace(
        candidate, bindings=replace(candidate.bindings, check=slow)
    )
    who = chat("arms-S")
    async with running(server) as wire:
        first = await wire.call(who, "fixture_start", {"slot": "R3-SYN-JOB-01"})
        second = await wire.call(who, "fixture_start", {"slot": "R3-SYN-JOB-02"})
        await server.seal(who, str(first.data["job"]))
        task = asyncio.ensure_future(wire.call(who, "fixture_unrelated_read"))
        assert await asyncio.to_thread(paused.wait, WAIT_S)  # nosec B101 - pytest assertion
        server.adapter = control  # switch arms while the call is in flight
        release.set()
        in_flight = await task
        await server.seal(who, str(second.data["job"]))
        after = await wire.call(who, "fixture_unrelated_read")
    assert in_flight.hints  # nosec B101 - pytest assertion
    assert HINT_FIELD in in_flight.result["structuredContent"]  # nosec B101 - pytest assertion
    unhinted = cp.frozen()["c_prime"]["wire_legacy"]["unhinted"]
    assert after.raw.decode() == unhinted and after.row["ja_hint"] == "0"  # nosec B101 - pytest assertion
    states = sorted(str(s) for (s,) in ledger_rows(server, "SELECT state FROM emit"))
    assert states == ["EMITTED", "PENDING"]  # nosec B101 - pytest assertion
