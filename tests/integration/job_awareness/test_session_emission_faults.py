"""E2 S2: §2.6 pause points, retire, cancel and DB write failures."""

import asyncio
import sqlite3
from dataclasses import replace

import pytest

from binnacle.features.commands.job_awareness import session_serving as serving
from binnacle.features.commands.job_awareness.models import Success, VerifiedRunGrant
from binnacle.features.commands.job_awareness.session_binding import LabFailure
from binnacle.features.commands.job_awareness.session_emission import emit_hint
from tests.integration.job_awareness.emission_support import (
    ORIGINAL,
    POINTS,
    Adapter,
    allocate,
    binding_of,
    emit_states,
    run,
)
from tests.unit.core.job_awareness.session_support import Lab, make_lab


def _retire_target(lab: Lab, name: str) -> str:
    entries = sorted(
        binding_of(lab, name).jobs.values(),
        key=lambda e: e.job.canonical_key,
    )
    return entries[0].handle


@pytest.mark.parametrize("point", POINTS)
def test_fenced_retire_waits_and_hint_is_emitted_while_live(tmp_path, point):
    lab = make_lab(tmp_path / "phase")
    allocate(lab, "A", 1)
    handle = _retire_target(lab, "A")
    tasks = []

    async def pause(at):
        if at == point:
            tasks.append(
                asyncio.ensure_future(serving.retire(lab.lab, lab.key("A"), handle))
            )
            for _ in range(5):
                await asyncio.sleep(0)
            assert not tasks[0].done()

    async def scenario():
        result = await emit_hint(
            lab.lab,
            lab.outcome("A"),
            ORIGINAL,
            execution=None,
            adapter=Adapter(pause=pause),
            checkpoint=pause,
        )
        return result, await tasks[0]

    result, retired = asyncio.run(scenario())
    assert result is not ORIGINAL and retired is True
    assert set(emit_states(lab).values()) == {"EMITTED"}
    assert lab.rows("SELECT state FROM alloc") == [("RETIRED",)]


@pytest.mark.parametrize("point", POINTS)
def test_retire_bypassing_the_fence_is_suppressed_and_aborted(tmp_path, point):
    lab = make_lab(tmp_path / "phase")
    allocate(lab, "A", 2)
    handle = _retire_target(lab, "A")

    async def pause(at):
        if at == point:
            assert serving.retire_unfenced(lab.lab, lab.key("A"), handle)

    result = run(lab, "A", Adapter(pause=pause), checkpoint=pause)
    assert result is ORIGINAL
    assert set(emit_states(lab).values()) == {"ABORTED"}
    assert run(lab, "A", Adapter()) is ORIGINAL  # the surviving job is not re-hinted


def test_retire_before_the_fence_reserves_nothing(tmp_path):
    lab = make_lab(tmp_path / "phase")
    allocate(lab, "A", 1)
    assert asyncio.run(serving.retire(lab.lab, lab.key("A"), _retire_target(lab, "A")))
    adapter = Adapter()
    assert run(lab, "A", adapter) is ORIGINAL and adapter.routes == []
    assert set(emit_states(lab).values()) == {"PENDING"}


@pytest.mark.parametrize("point", POINTS)
def test_cancel_at_each_pause_point_aborts(tmp_path, point):
    lab = make_lab(tmp_path / "phase")
    allocate(lab, "A", 2)

    async def scenario():
        reached = asyncio.Event()

        async def pause(at):
            if at == point:
                reached.set()
                await asyncio.Event().wait()

        task = asyncio.ensure_future(
            emit_hint(
                lab.lab,
                lab.outcome("A"),
                ORIGINAL,
                execution=None,
                adapter=Adapter(pause=pause),
                checkpoint=pause,
            )
        )
        await reached.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # The fence is free again after cancellation.
        return await emit_hint(
            lab.lab, lab.outcome("A"), ORIGINAL, execution=None, adapter=Adapter()
        )

    assert asyncio.run(scenario()) is ORIGINAL
    assert set(emit_states(lab).values()) == {"ABORTED"}


@pytest.mark.parametrize("op", ["lab:reserve", "lab:commit"])
def test_db_write_failure_returns_original_and_never_rehints(tmp_path, op):
    armed = {"on": True}

    def fault(point):
        if armed["on"] and point == op:
            raise LabFailure()

    lab = make_lab(tmp_path / "phase", fault=fault)
    allocate(lab, "A", 2)
    assert run(lab, "A", Adapter()) is ORIGINAL
    armed["on"] = False
    later = run(lab, "A", Adapter())
    if op == "lab:reserve":  # rolled back: never hinted, so one hint later
        assert later is not ORIGINAL and set(emit_states(lab).values()) == {"EMITTED"}
    else:  # emit failed after render: ABORTED, never re-hinted
        assert later is ORIGINAL and set(emit_states(lab).values()) == {"ABORTED"}


def test_reset_failure_aborts(tmp_path):
    def fault(point):
        if point == "lab:commit":
            raise LabFailure()

    lab = make_lab(tmp_path / "phase", fault=fault)
    allocate(lab, "A", 2)
    assert run(lab, "A", Adapter(render=lambda route: ())) is ORIGINAL
    assert set(emit_states(lab).values()) == {"ABORTED"}


def test_abort_failure_leaves_reserved_unhintable_until_cold_start(tmp_path):
    armed = {"on": True}

    def fault(point):
        if armed["on"] and point in ("lab:commit", "lab:abort"):
            raise LabFailure()

    lab = make_lab(tmp_path / "phase", fault=fault)
    allocate(lab, "A", 2)
    assert run(lab, "A", Adapter()) is ORIGINAL
    assert set(emit_states(lab).values()) == {"RESERVED"}
    armed["on"] = False
    assert run(lab, "A", Adapter()) is ORIGINAL
    assert [e["event"] for e in lab.events][-1] == "ja_abort_unwritten"
    restarted = make_lab(tmp_path / "phase", clock=lab.clock)
    assert set(emit_states(restarted).values()) == {"ABORTED"}


def test_reserve_and_commit_rowcount_anomalies(tmp_path):
    ref = []

    class Flip:
        """Changes one emit row between the eligibility read and the reserve."""

        def query(self, grant, snapshot):
            lab_ref = ref[0]
            if snapshot.job == min(
                lab_ref.lab.table.get(lab_ref.key("A").kd).jobs,
                key=lambda j: j.canonical_key,
            ):
                db = sqlite3.connect(lab_ref.lab.ledger.path)
                db.execute(
                    "UPDATE emit SET state='ABORTED', final_ms=1 WHERE jobref=?",
                    (snapshot.job.canonical_key,),
                )
                db.commit()
                db.close()
            return lab_ref.lab.authority.store.query(grant, snapshot)

    lab = make_lab(tmp_path / "phase", receipts=Flip())
    ref.append(lab)
    allocate(lab, "A", 2)
    adapter = Adapter()
    result = run(lab, "A", adapter)
    assert result is not ORIGINAL and len(adapter.routes[0].jobs) == 1
    assert any(e.get("reason") == "reserve_rowcount" for e in lab.events)

    lab2 = make_lab(tmp_path / "phase2")
    allocate(lab2, "A", 1)

    async def steal(at):
        if at == "before_commit":
            db = sqlite3.connect(lab2.lab.ledger.path)
            db.execute(
                "UPDATE emit SET reservation_id=? WHERE state='RESERVED'", ("0" * 32,)
            )
            db.commit()
            db.close()

    assert run(lab2, "A", Adapter(), checkpoint=steal) is ORIGINAL
    assert any(e.get("reason") == "abort_rowcount" for e in lab2.events)
    assert set(emit_states(lab2).values()) == {
        "RESERVED"
    }  # foreign rid: never re-hintable
    assert run(lab2, "A", Adapter()) is ORIGINAL


def test_eligibility_read_failure_returns_original(tmp_path):
    lab = make_lab(tmp_path / "phase")
    allocate(lab, "A", 1)
    original_read = lab.lab.ledger.read

    def broken():
        raise LabFailure()

    lab.lab.ledger.read = broken
    try:
        assert run(lab, "A", Adapter()) is ORIGINAL
    finally:
        lab.lab.ledger.read = original_read
    assert set(emit_states(lab).values()) == {"PENDING"}


def _mutate_memory(lab: Lab) -> None:
    binding = binding_of(lab, "A")
    job = next(iter(binding.jobs))
    binding.jobs[job] = replace(binding.jobs[job])


def _mutate_lab_row(lab: Lab) -> None:
    db = sqlite3.connect(lab.lab.ledger.path)
    db.execute("UPDATE alloc SET state='DENY_FOREVER'")
    db.commit()
    db.close()


def _revoke_grant(lab: Lab) -> None:
    grant = binding_of(lab, "A").grant
    assert grant is not None
    assert isinstance(lab.lab.authority.revoke(grant), Success)


class _OtherGrant(VerifiedRunGrant):
    @property
    def authority_handle(self) -> object:
        return self


def _swap_grant(lab: Lab) -> None:
    binding_of(lab, "A").grant = _OtherGrant()


@pytest.mark.parametrize(
    "mutate",
    [_mutate_memory, _mutate_lab_row, _revoke_grant, _swap_grant],
    ids=["memory", "lab-row", "grant-revoked", "grant-swapped"],
)
@pytest.mark.parametrize("point", ["after_adapt", "before_commit"])
def test_final_validation_detects_each_disagreement(tmp_path, mutate, point):
    lab = make_lab(tmp_path / "phase")
    allocate(lab, "A", 1)

    async def pause(at):
        if at == point:
            mutate(lab)

    assert run(lab, "A", Adapter(), checkpoint=pause) is ORIGINAL
    assert set(emit_states(lab).values()) == {"ABORTED"}


def test_failed_or_foreign_receipts_are_not_eligible(tmp_path):
    from binnacle.features.commands.job_awareness.models import (
        BoundaryError,
        ErrorCode,
        Failure,
    )

    class Denying:
        def query(self, grant, snapshot):
            return Failure(BoundaryError(ErrorCode.DENIED))

    lab = make_lab(tmp_path / "phase", receipts=Denying())
    allocate(lab, "A", 2)
    assert run(lab, "A", Adapter()) is ORIGINAL
    ref = []

    class Foreign:
        def query(self, grant, snapshot):
            result = ref[0].lab.authority.store.query(grant, snapshot)
            other = replace(snapshot.job, job_id="f" * 12)
            return Success(replace(result.value, job=other))

    lab2 = make_lab(tmp_path / "phase2", receipts=Foreign())
    ref.append(lab2)
    allocate(lab2, "A", 1)
    assert run(lab2, "A", Adapter()) is ORIGINAL
    assert set(emit_states(lab2).values()) == {"PENDING"}
