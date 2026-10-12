"""Review TEXTU-G3-01/02: a routed adapter's configuration is immutable.

Assigning or deleting any field of a routed ``HintAdapter`` (except the
diagnostic ``last_meter``) raises, so an admitted call can never observe a
different carrier, ``enabled``, ``exclusive``, bindings, tool or server stamp.
The reviewer's replays (a change paused inside the render, and inside the
final ``_valid`` of the EMITTED commit) therefore cannot be built: the
assignment raises, and the call completes with the configuration it was
admitted with. A new arm is a new adapter; a call keeps the adapter it was
dispatched with (bounded snapshot semantics), so the arm controller switches
arms only between calls. Non-routed adapters and ``adapt()`` are unchanged.
"""

import asyncio
import dataclasses
from dataclasses import replace
from threading import Event

import pytest

from binnacle.features.commands.job_awareness import session_emission
from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.features.commands.job_awareness.session_emission import emit_hint
from binnacle.mcp.job_awareness_hint import META_KEY, HintAdapter
from tests.contracts.job_awareness.e2_composition import E2Server, chat, running
from tests.contracts.job_awareness.e2_scoring import ledger_rows
from tests.contracts.job_awareness.routed_support import RoutedLab
from tests.contracts.job_awareness.synthetic_app import in_loop
from tests.contracts.job_awareness.test_hint_routed_emission import note
from tests.contracts.job_awareness.test_hint_schema_support import executed

META, TEXT = HintCarrier.META, HintCarrier.TEXT
ARMS = [(META, True), (TEXT, False)]
ARM_IDS = ["schema-META", "TEXT-U"]
FIELDS = [f.name for f in dataclasses.fields(HintAdapter) if f.name != "last_meter"]
#: The in-flight changes of the reviewer's replays.
CHANGES = {"carrier": None, "enabled": False, "exclusive": False}
WAIT_S = 10


def other_carrier(carrier):
    return TEXT if carrier is META else META


def attempts(adapter) -> list[str]:
    """Try every in-flight change; return the names that did NOT raise."""
    allowed = []
    for name, value in CHANGES.items():
        new = other_carrier(adapter.carrier) if name == "carrier" else value
        try:
            setattr(adapter, name, new)
        except AttributeError:
            continue
        allowed.append(name)
    return allowed


def emit_states(server: E2Server) -> set[str]:
    return {str(s) for (s,) in ledger_rows(server, "SELECT state FROM emit")}


@pytest.mark.parametrize(("carrier", "structured"), ARMS, ids=ARM_IDS)
def test_every_routed_field_is_immutable(carrier, structured):
    with RoutedLab(1) as lab:
        adapter = lab.routed(structured=structured, enabled=True, carrier=carrier)
        before = dict(vars(adapter))
        for name in FIELDS:
            with pytest.raises(AttributeError, match="immutable"):
                setattr(adapter, name, getattr(adapter, name))
            with pytest.raises(AttributeError, match="immutable"):
                delattr(adapter, name)
        with pytest.raises(AttributeError, match="immutable"):
            adapter.bind_server(object())
        adapter.last_meter = None  # diagnostic only
        assert vars(adapter) == before | {"last_meter": None}  # nosec B101 - pytest assertion
        other = replace(adapter, enabled=False)  # a new arm is a new adapter
        assert other is not adapter and adapter.enabled is True  # nosec B101 - pytest assertion
        assert other.routed_carrier is carrier and other.enabled is False  # nosec B101 - pytest assertion


def test_non_routed_adapters_stay_mutable():
    with RoutedLab(1) as lab:
        adapter = lab.adapter(enabled=True, carrier=TEXT)
        adapter.enabled = False
        adapter.carrier = META
        adapter.bind_server(object())
        assert (adapter.enabled, adapter.carrier, adapter.server_info) == (  # nosec B101 - pytest assertion
            False,
            META,
            None,
        )


class Pause:
    """Pause the worker in ``check``; try the in-flight changes from there."""

    def __init__(self, check):
        self.check, self.entered, self.release = check, Event(), Event()
        self.allowed: list[str] | None = None
        self.adapter = None

    def __call__(self, grant, job, scopes):
        if self.allowed is None:
            self.allowed = attempts(self.adapter)
        return self.check(grant, job, scopes)


@pytest.mark.parametrize(("carrier", "structured"), ARMS, ids=ARM_IDS)
@in_loop
async def test_in_flight_changes_inside_the_render_cannot_be_made(
    tmp_path, carrier, structured
):
    server = E2Server(tmp_path / "phase", carrier=carrier, structured=structured)
    pause = Pause(server.adapter.bindings.check)
    server.adapter = replace(
        server.adapter, bindings=replace(server.adapter.bindings, check=pause)
    )
    pause.adapter = server.adapter
    who = chat("inflight")
    async with running(server) as wire:
        start = await wire.call(who, "fixture_start", {"slot": "R3-SYN-JOB-01"})
        await server.seal(who, str(start.data["job"]))
        call = await wire.call(who, "fixture_unrelated_read")
    assert pause.allowed == []  # nosec B101 - pytest assertion
    hint_in_meta = META_KEY in (call.result.get("_meta") or {})
    assert call.hints and hint_in_meta is (carrier is META)  # nosec B101 - pytest assertion
    assert ("structuredContent" in call.result) is structured  # nosec B101 - pytest assertion
    assert emit_states(server) == {"EMITTED"}  # nosec B101 - pytest assertion


@pytest.mark.parametrize(("carrier", "structured"), ARMS, ids=ARM_IDS)
@in_loop
async def test_in_flight_changes_inside_the_final_commit_cannot_be_made(
    tmp_path, carrier, structured, monkeypatch
):
    """The reviewer's LATE_COMMIT_DRIFT: pause inside the second ``_valid``."""
    server = E2Server(tmp_path / "phase", carrier=carrier, structured=structured)
    who = chat("late")
    handle = await server.lab.start_fixture(server.outcome(who), "R3-SYN-JOB-01")
    await server.seal(who, str(handle))
    real, seen = session_emission._valid, []

    def valid(*args, **kwargs):
        seen.append(attempts(server.adapter) if len(seen) == 1 else [])
        return real(*args, **kwargs)

    monkeypatch.setattr(session_emission, "_valid", valid)
    value = note(structured)
    result = await emit_hint(
        server.lab,
        server.outcome(who),
        value,
        execution=executed(value, server.tool),
        adapter=server.adapter,
    )
    await server.workers.close()
    assert len(seen) == 2 and seen == [[], []]  # nosec B101 - pytest assertion
    assert result is not value  # nosec B101 - pytest assertion
    assert (META_KEY in (result.meta or {})) is (carrier is META)  # nosec B101 - pytest assertion
    assert len(result.content) == (1 if carrier is META else 2)  # nosec B101 - pytest assertion
    assert emit_states(server) == {"EMITTED"}  # nosec B101 - pytest assertion


@in_loop
async def test_arm_switch_is_a_new_adapter_and_calls_keep_their_snapshot(tmp_path):
    """Bounded snapshot: an admitted call finishes on its own adapter; the
    next call uses the new arm. The controller switches arms between calls."""
    server = E2Server(tmp_path / "phase")
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
    who = chat("arms")
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
    assert in_flight.hints  # nosec B101 - pytest assertion - its own (candidate) snapshot
    assert not after.hints and after.row["ja_hint"] == "0"  # nosec B101 - pytest assertion
    states = sorted(str(s) for (s,) in ledger_rows(server, "SELECT state FROM emit"))
    assert states == ["EMITTED", "PENDING"]  # nosec B101 - pytest assertion
