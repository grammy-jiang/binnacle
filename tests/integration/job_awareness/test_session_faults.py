"""E2 S2: fault injection across both ledgers, crash and restart (§2.5).

Two physical stores, no cross-store transaction. Every affected JobRef must be
DENIED forever, no JobRef is served to a different key, no route is published
without lab LIVE, and the ReceiptStore v1 exact-schema check still passes.
"""

import asyncio
import multiprocessing
import os
import sqlite3

import pytest

from binnacle.features.commands.job_awareness import receipt_schema
from binnacle.features.commands.job_awareness import session_serving as serving
from binnacle.features.commands.job_awareness.models import Success
from binnacle.features.commands.job_awareness.receipt_schema import SCHEMA, VERSION
from binnacle.features.commands.job_awareness.receipt_store import ReceiptStore
from binnacle.features.commands.job_awareness.session_binding import LabFailure
from binnacle.features.commands.job_awareness.session_emission import emit_hint
from binnacle.features.commands.job_awareness.session_lab import LabError
from tests.unit.core.job_awareness.session_support import (
    Lab,
    ManualClock,
    make_lab,
    scan_phase,
)

STEP_POINTS = (
    "alloc:1",
    "alloc:2:seal",
    "alloc:2:revoke",
    "alloc:2:issue",
    "alloc:3",
    "alloc:4",
    "alloc:5:publish",
    "alloc:5:live",
)
LAB_POINTS = ("lab:owner", "lab:granted", "lab:live")
NOT_SUSPENDED = {"alloc:1", "alloc:2:seal", "lab:owner", "lab:live"}


def receipt_schema_ok(lab: Lab) -> bool:
    path = lab.phase / "receipt" / "receipt.sqlite"
    db = sqlite3.connect(path)
    try:
        shape = {
            r[0]
            for r in db.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL")
        }
        version = db.execute("PRAGMA user_version").fetchone()[0]
    finally:
        db.close()
    store = ReceiptStore(path, clock=lambda: lab.clock.wall_ms + 10**6)
    return (
        shape == set(SCHEMA)
        and version == VERSION
        and isinstance(store.read_transaction(lambda tx: None), Success)
    )


def assert_invariants(lab: Lab) -> None:
    """Routes exist only for lab-LIVE rows of the same key; no raw values."""
    for binding in lab.lab.table._keys.values():
        for job in binding.jobs:
            rows = lab.rows(
                "SELECT kd,state FROM alloc WHERE jobref=?", (job.canonical_key,)
            )
            assert rows == [(binding.key.kd, "LIVE")]
    assert receipt_schema_ok(lab)
    assert scan_phase(lab.phase, lab.events) == []


def armed_fault(point: str, error: Exception | None = None):
    state = {"armed": False}

    def fault(seen: str) -> None:
        if state["armed"] and seen == point:
            raise error or LabFailure()

    return state, fault


@pytest.mark.parametrize("point", STEP_POINTS + LAB_POINTS)
def test_in_process_failure_at_each_step(tmp_path, point):
    state, fault = armed_fault(point)
    lab = make_lab(tmp_path / "phase", fault=fault)
    first = lab.start("A", "R3-SYN-JOB-01")
    assert isinstance(first, str)
    state["armed"] = True
    assert lab.start("A", "R3-SYN-JOB-02") is LabError.DENIED
    state["armed"] = False
    binding = lab.lab.table.get(lab.key("A").kd)
    assert [e.slot for e in binding.jobs.values()] == ["R3-SYN-JOB-01"]
    second_rows = lab.rows("SELECT state FROM alloc WHERE slot='R3-SYN-JOB-02'")
    assert second_rows in ([], [("DENY_FOREVER",)])
    assert (second_rows == []) is (point == "lab:owner")
    suspended = point not in NOT_SUSPENDED
    assert binding.suspended is suspended
    key_state = lab.rows("SELECT state FROM keys WHERE kd=?", (lab.key("A").kd,))
    assert key_state == [("SUSPENDED" if suspended else "ACTIVE",)]
    page = serving.read_page(lab.lab, lab.outcome("A"), first, 0)
    assert isinstance(page, dict) is (not suspended)
    assert serving.read_page(lab.lab, lab.outcome("B"), first, 0) is LabError.DENIED
    # A different key is unaffected by the failure.
    assert isinstance(lab.start("B", "R3-SYN-JOB-03"), str)
    assert_invariants(lab)


def test_deny_write_also_failing_still_publishes_nothing(tmp_path):
    state = {"armed": False}

    def fault(seen: str) -> None:
        if state["armed"] and seen in ("alloc:3", "lab:deny"):
            raise LabFailure()

    lab = make_lab(tmp_path / "phase", fault=fault)
    state["armed"] = True
    assert lab.start("A", "R3-SYN-JOB-01") is LabError.DENIED
    state["armed"] = False
    assert lab.rows("SELECT state FROM alloc") == [("GRANTED",)]
    assert lab.lab.table.get(lab.key("A").kd) is None
    assert any(e["event"] == "ja_deny_unwritten" for e in lab.events)
    assert (
        serving.read_page(lab.lab, lab.outcome("A"), "R3-SYN-JOB-01", 0)
        is LabError.DENIED
    )
    restarted = make_lab(tmp_path / "phase", clock=lab.clock)
    assert restarted.rows("SELECT state FROM alloc") == [("DENY_FOREVER",)]
    assert_invariants(restarted)


@pytest.mark.parametrize("point", ["alloc:1", "alloc:2:revoke"])
def test_receipt_store_busy(tmp_path, point):
    """A held ReceiptStore connection makes its next transaction return BUSY."""
    state = {"armed": False, "held": False}

    def fault(seen: str) -> None:
        if state["armed"] and seen == point and not state["held"]:
            state["held"] = receipt_schema._PROCESS_CONNECTION.acquire(blocking=False)

    lab = make_lab(tmp_path / "phase", fault=fault)
    assert isinstance(lab.start("A", "R3-SYN-JOB-01"), str)
    state["armed"] = True
    try:
        result = lab.start("A", "R3-SYN-JOB-02")
    finally:
        if state["held"]:
            receipt_schema._PROCESS_CONNECTION.release()
    assert state["held"] and result is LabError.DENIED
    assert lab.rows("SELECT state FROM alloc WHERE slot='R3-SYN-JOB-02'") == [
        ("DENY_FOREVER",)
    ]
    assert lab.lab.table.get(lab.key("A").kd).suspended is (point == "alloc:2:revoke")
    assert_invariants(lab)


class _Routed:
    def __init__(self, route):
        self.result, self.rendered = {"hint": True}, tuple(route.jobs)


class _Passthrough:
    async def adapt_routed(self, original, *, execution, route):
        return _Routed(route)


def _crash_child(phase, point, emit_point):
    armed = {"on": False}

    def fault(seen: str) -> None:
        if armed["on"] and seen == point:
            os._exit(70)

    async def pause(at: str) -> None:
        if at == emit_point:
            os._exit(70)

    lab = make_lab(phase, fault=fault)
    assert isinstance(lab.start("A", "R3-SYN-JOB-01"), str)
    armed["on"] = True
    if emit_point is None:
        lab.start("A", "R3-SYN-JOB-02")
    else:
        coroutine = emit_hint(
            lab.lab,
            lab.outcome("A"),
            {},
            execution=None,
            adapter=_Passthrough(),
            checkpoint=pause,
        )
        asyncio.run(coroutine)
    os._exit(71)


def crash(phase, point, emit_point=None) -> int | None:
    process = multiprocessing.get_context("fork").Process(
        target=_crash_child, args=(phase, point, emit_point)
    )
    process.start()
    process.join(30)
    return process.exitcode


@pytest.mark.parametrize("point", STEP_POINTS + LAB_POINTS)
def test_kill_after_each_step_then_restart(tmp_path, point):
    phase = tmp_path / "phase"
    assert crash(phase, point) == 70
    lab = make_lab(phase, clock=ManualClock())
    states = dict(lab.rows("SELECT slot,state FROM alloc"))
    assert set(states.values()) <= {"DENY_FOREVER"}
    assert states.get("R3-SYN-JOB-01") == "DENY_FOREVER"
    assert lab.lab.table._keys == {}
    old = lab.rows("SELECT DISTINCT kd FROM alloc")
    assert all(kd != lab.key("A").kd for (kd,) in old)
    for selector in ("R3-SYN-JOB-01", "R3-SYN-JOB-02", "j_000000000000"):
        assert (
            serving.read_page(lab.lab, lab.outcome("A"), selector, 0) is LabError.DENIED
        )
    fresh = lab.start("A", "R3-SYN-JOB-02")
    assert isinstance(fresh, str)
    page = serving.read_page(lab.lab, lab.outcome("A"), fresh, 0)
    assert isinstance(page, dict) and page["slot"] == "R3-SYN-JOB-02"
    assert serving.read_page(lab.lab, lab.outcome("B"), fresh, 0) is LabError.DENIED
    assert_invariants(lab)


@pytest.mark.parametrize("emit_point", ["after_reserve", "before_commit"])
def test_kill_during_emission_then_cold_start_aborts(tmp_path, emit_point):
    phase = tmp_path / "phase"
    assert crash(phase, None, emit_point) == 70
    lab = make_lab(phase, clock=ManualClock())
    assert lab.rows("SELECT state FROM emit") == [("ABORTED",)]
    assert lab.rows("SELECT state FROM alloc") == [("DENY_FOREVER",)]
    assert_invariants(lab)


def test_cold_start_refuses_when_sweep_fails(tmp_path):
    lab = make_lab(tmp_path / "phase")
    assert isinstance(lab.start("A", "R3-SYN-JOB-01"), str)

    def fault(seen: str) -> None:
        if seen == "lab:sweep":
            raise LabFailure()

    blocked = make_lab(tmp_path / "phase", clock=lab.clock, fault=fault, start=False)
    assert blocked.lab.start() is False and blocked.lab.ready is False
    assert blocked.lab.keyed(lab.outcome("A")) is None
