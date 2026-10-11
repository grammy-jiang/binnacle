"""E2 S2: once-only emission under the per-key fence (design §2.6 tests)."""

import asyncio
from dataclasses import replace

import pytest

from binnacle.features.commands.job_awareness import session_serving as serving
from binnacle.features.commands.job_awareness.models import ReceiptState, Success
from binnacle.features.commands.job_awareness.session_emission import emit_hint
from binnacle.features.commands.job_awareness.session_lab import LabConfig
from binnacle.features.commands.job_awareness.session_route import (
    RouteOutcome,
    RouteStatus,
)
from tests.integration.job_awareness.emission_support import (
    ORIGINAL,
    Adapter,
    Routed,
    allocate,
    binding_of,
    emit_states,
    run,
)
from tests.unit.core.job_awareness.session_support import make_lab, scan_phase


@pytest.mark.parametrize("count", [3, 4, 8])
def test_at_most_two_per_call_then_the_next(tmp_path, count):
    lab = make_lab(tmp_path / "phase")
    allocate(lab, "A", count)
    adapter = Adapter()
    seen = []
    for _ in range((count + 1) // 2):
        result = run(lab, "A", adapter)
        assert result is not ORIGINAL
        route = adapter.routes[-1]
        assert 1 <= len(route.jobs) <= 2
        assert list(route.jobs) == sorted(route.jobs, key=lambda j: j.canonical_key)
        assert result["hint"] == [j.canonical_key for j in route.jobs]
        seen.extend(result["hint"])
    assert run(lab, "A", adapter) is ORIGINAL
    assert len(seen) == len(set(seen)) == count
    assert seen == sorted(seen)
    assert set(emit_states(lab).values()) == {"EMITTED"}
    assert scan_phase(lab.phase, lab.events) == []


class Receipts:
    """Read-only receipt port with injected states per slot."""

    def __init__(self, lab_ref, states):
        self.lab_ref, self.states = lab_ref, states

    def query(self, grant, snapshot):
        result = self.lab_ref[0].authority.store.query(grant, snapshot)
        binding_slots = {
            e.job: e.slot
            for b in self.lab_ref[0].table._keys.values()
            for e in b.jobs.values()
        }
        state = self.states.get(binding_slots.get(snapshot.job))
        if state is None or not isinstance(result, Success):
            return result
        return Success(replace(result.value, state=state))


def test_complete_and_expired_never_block_and_partial_follows(tmp_path):
    ref = []
    states = {
        "R3-SYN-JOB-01": ReceiptState.COMPLETE,
        "R3-SYN-JOB-02": ReceiptState.OUTPUT_EXPIRED,
        "R3-SYN-JOB-03": ReceiptState.PARTIAL,
    }
    lab = make_lab(tmp_path / "phase", receipts=Receipts(ref, states))
    ref.append(lab.lab)
    allocate(lab, "A", 5)
    adapter = Adapter()
    first = run(lab, "A", adapter)
    slots = {e.job: e.slot for e in binding_of(lab, "A").jobs.values()}
    route = adapter.routes[0].jobs
    assert {slots[j] for j in route} == {"R3-SYN-JOB-04", "R3-SYN-JOB-05"}
    assert list(route) == sorted(route, key=lambda j: j.canonical_key)
    second = run(lab, "A", adapter)
    assert [slots[j] for j in adapter.routes[1].jobs] == [
        "R3-SYN-JOB-03"
    ]  # fewer than 2
    assert first is not ORIGINAL and second is not ORIGINAL
    assert run(lab, "A", adapter) is ORIGINAL
    by_slot = {slots[j]: emit_states(lab)[j.canonical_key] for j in slots}
    assert by_slot == {
        "R3-SYN-JOB-01": "PENDING",
        "R3-SYN-JOB-02": "PENDING",
        "R3-SYN-JOB-03": "EMITTED",
        "R3-SYN-JOB-04": "EMITTED",
        "R3-SYN-JOB-05": "EMITTED",
    }


def test_failing_receipt_port_and_foreign_receipt_are_skipped(tmp_path):
    class Broken:
        def query(self, grant, snapshot):
            raise RuntimeError("port")

    lab = make_lab(tmp_path / "phase", receipts=Broken())
    allocate(lab, "A", 1)
    assert run(lab, "A", Adapter()) is ORIGINAL
    assert set(emit_states(lab).values()) == {"PENDING"}


def test_render_none_resets_to_pending_and_subset_rendering(tmp_path):
    lab = make_lab(tmp_path / "phase")
    allocate(lab, "A", 2)
    assert run(lab, "A", Adapter(render=lambda route: ())) is ORIGINAL
    assert set(emit_states(lab).values()) == {"PENDING"}
    assert {row[0] for row in lab.rows("SELECT version FROM emit")} == {2}
    result = run(lab, "A", Adapter(render=lambda route: route.jobs[1:]))
    states = emit_states(lab)
    rendered = result["hint"]
    assert len(rendered) == 1 and states[rendered[0]] == "EMITTED"
    assert sorted(states.values()) == ["EMITTED", "PENDING"]
    final = run(lab, "A", Adapter())
    assert final["hint"] != rendered
    assert set(emit_states(lab).values()) == {"EMITTED"}


@pytest.mark.parametrize(
    "lie",
    [
        lambda original, route: Routed(
            {"hint": 1}, route.jobs + route.jobs[:1]
        ),  # duplicate
        lambda original, route: Routed(
            {"hint": 1}, (replace(route.jobs[0], job_id="f" * 12),)
        ),
        lambda original, route: Routed(original, route.jobs),  # original with rendered
        lambda original, route: Routed({"hint": 1}, ()),  # changed without rendered
        lambda original, route: Routed({"hint": 1}, list(route.jobs)),
    ],
    ids=[
        "duplicate",
        "foreign",
        "original-with-rendered",
        "changed-without-rendered",
        "list",
    ],
)
def test_adapter_contract_violation_is_suppressed_and_aborted(tmp_path, lie):
    lab = make_lab(tmp_path / "phase")
    allocate(lab, "A", 2)
    assert run(lab, "A", Adapter(lie=lie)) is ORIGINAL
    assert set(emit_states(lab).values()) == {"ABORTED"}
    assert run(lab, "A", Adapter()) is ORIGINAL  # never re-hinted


def test_adapter_exception_returns_original_and_aborts(tmp_path):
    lab = make_lab(tmp_path / "phase")
    allocate(lab, "A", 1)
    assert run(lab, "A", Adapter(raises=RuntimeError("adapter"))) is ORIGINAL
    assert set(emit_states(lab).values()) == {"ABORTED"}
    assert [e["emit_state"] for e in lab.events if e["event"] == "ja_hint"] == [
        "ABORTED"
    ]


def test_no_route_no_binding_suspended_and_closed(tmp_path):
    lab = make_lab(tmp_path / "phase")
    adapter = Adapter()
    unkeyed = RouteOutcome(RouteStatus.NO_SESSION)
    assert (
        asyncio.run(
            emit_hint(lab.lab, unkeyed, ORIGINAL, execution=None, adapter=adapter)
        )
        is ORIGINAL
    )
    assert run(lab, "A", adapter) is ORIGINAL  # no binding
    allocate(lab, "A", 1)
    asyncio.run(serving.close(lab.lab, lab.key("A")))
    assert run(lab, "A", adapter) is ORIGINAL  # binding without grant
    allocate(lab, "B", 1)
    asyncio.run(serving.suspend(lab.lab, lab.key("B")))
    assert run(lab, "B", adapter) is ORIGINAL
    assert adapter.routes == []


def test_fence_timeout_returns_original_without_reservation(tmp_path):
    lab = make_lab(tmp_path / "phase", config=LabConfig(fence_timeout_s=0.05))
    allocate(lab, "A", 1)

    async def scenario():
        lock = lab.lab.fences.lock(lab.key("A").kd)
        await lock.acquire()
        try:
            return await emit_hint(
                lab.lab, lab.outcome("A"), ORIGINAL, execution=None, adapter=Adapter()
            )
        finally:
            lock.release()

    assert asyncio.run(scenario()) is ORIGINAL
    assert set(emit_states(lab).values()) == {"PENDING"}


@pytest.mark.timeout(300)
@pytest.mark.parametrize("calls", [2, 8])
def test_same_session_concurrency_100_rounds(tmp_path, calls):
    lab = None
    for round_index in range(100):
        if round_index % 30 == 0:
            lab = make_lab(tmp_path / f"phase-{round_index}")
        name = f"chat-{round_index}"
        allocate(lab, name, 3)

        async def burst(lab=lab, name=name):
            outcome = lab.outcome(name)
            return await asyncio.gather(
                *(
                    emit_hint(
                        lab.lab, outcome, ORIGINAL, execution=None, adapter=Adapter()
                    )
                    for _ in range(calls)
                )
            )

        results = asyncio.run(burst())
        hinted = [
            key
            for result in results
            if result is not ORIGINAL
            for key in result["hint"]
        ]
        assert len(hinted) == len(set(hinted))
        states = emit_states(lab, name)
        assert {k for k, v in states.items() if v == "EMITTED"} == set(hinted)
        assert len(hinted) == min(3, 2 * calls)


def test_two_keys_interleaved_never_cross(tmp_path):
    lab = make_lab(tmp_path / "phase")
    allocate(lab, "A", 3)
    allocate(lab, "B", 3)
    adapter = Adapter()

    async def interleave():
        calls = []
        for _ in range(3):
            for name in ("A", "B"):
                calls.append(
                    emit_hint(
                        lab.lab,
                        lab.outcome(name),
                        ORIGINAL,
                        execution=name,
                        adapter=adapter,
                    )
                )
        return await asyncio.gather(*calls)

    results = asyncio.run(interleave())
    jobs_a = {j.canonical_key for j in binding_of(lab, "A").jobs}
    jobs_b = {j.canonical_key for j in lab.lab.table.get(lab.key("B").kd).jobs}
    for index, result in enumerate(results):
        if result is ORIGINAL:
            continue
        mine = jobs_a if index % 2 == 0 else jobs_b
        assert set(result["hint"]) <= mine
    for route in adapter.routes:
        owner = lab.lab.table.get(route.key.kd)
        assert set(route.jobs) <= set(owner.jobs)
    assert set(emit_states(lab).values()) == {"EMITTED"}
