"""E2 S5 / CA-2 on the real lab ledger: once-only emission around adapt_routed.

The S4 in-memory ``emit`` double is gone. Every test here drives the real S2
``emit_hint`` (per-key fence, reserve/emit/reset/abort SQL, final validation)
over the real ``SessionLab`` with the real ``HintAdapter.adapt_routed``,
``select_candidates`` and ``render_hint`` (design §2.6 tests).
"""

import asyncio
import sqlite3
from collections import Counter
from dataclasses import replace

import pytest
from fastmcp.tools.base import ToolResult
from mcp.types import TextContent

from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.features.commands.job_awareness.session_emission import emit_hint
from binnacle.mcp.job_awareness_hint import HintAdapter
from tests.contracts.job_awareness.e2_composition import (
    NOTE,
    E2Server,
    chat,
    hinted_keys,
)
from tests.contracts.job_awareness.e2_scoring import ledger_rows
from tests.contracts.job_awareness.synthetic_app import in_loop
from tests.contracts.job_awareness.test_hint_schema_support import executed


def note() -> ToolResult:
    return ToolResult(
        content=[TextContent(type="text", text=NOTE)],
        structured_content={"note": NOTE},
    )


def hinted(result: ToolResult) -> list[str]:
    blocks = [{"text": getattr(block, "text", "")} for block in result.content]
    return hinted_keys({"_meta": result.meta, "content": blocks})


async def allocate(server: E2Server, name: str, count: int, *, seal=True):
    who = chat(name)
    handles = []
    for index in range(count):
        started = await server.lab.start_fixture(
            server.outcome(who), f"R3-SYN-JOB-{index + 1:02d}"
        )
        assert isinstance(started, str)  # nosec B101 - pytest assertion
        if seal:
            await server.seal(who, started)
        handles.append(started)
    return who, handles


async def emission(server, who, *, adapter=None, checkpoint=None):
    value = note()
    receipt = executed(value, server.tool)
    result = await emit_hint(
        server.lab,
        server.outcome(who),
        value,
        execution=receipt,
        adapter=adapter or server.adapter,
        checkpoint=checkpoint,
    )
    return value, result


def states(server, who=None) -> dict[str, str]:
    rows = ledger_rows(server, "SELECT jobref,kd,state FROM emit")
    kd = None if who is None else server.key(who).kd
    return {str(j): str(s) for j, k, s in rows if kd is None or k == kd}


def keys_of(server, who) -> list[str]:
    binding = server.lab.table.get(server.key(who).kd)
    assert binding is not None  # nosec B101 - pytest assertion
    return sorted(job.canonical_key for job in binding.jobs)


@pytest.mark.parametrize("live", [3, 4, 8])
@in_loop
async def test_live_jobs_are_hinted_two_per_call_in_order(tmp_path, live):
    server = E2Server(tmp_path / "phase")
    who, _ = await allocate(server, "A", live)
    keys = keys_of(server, who)
    for start in range(0, live, 2):
        _, result = await emission(server, who)
        assert hinted(result) == keys[start : start + 2]  # nosec B101 - pytest assertion
    value, result = await emission(server, who)
    assert result is value  # nosec B101 - pytest assertion
    assert set(states(server).values()) == {"EMITTED"}  # nosec B101 - pytest assertion
    await server.workers.close()


@in_loop
async def test_fewer_than_two_and_unsealed_are_not_reserved(tmp_path):
    server = E2Server(tmp_path / "phase")
    who, _ = await allocate(server, "A", 1)
    await server.lab.start_fixture(server.outcome(who), "R3-SYN-JOB-09")  # unsealed
    _, result = await emission(server, who)
    assert len(hinted(result)) == 1  # nosec B101 - pytest assertion
    assert sorted(states(server).values()) == ["EMITTED", "PENDING"]  # nosec B101 - pytest assertion
    await server.workers.close()


@in_loop
async def test_unselected_and_render_none_reset_to_pending(tmp_path):
    server = E2Server(tmp_path / "phase")
    who, _ = await allocate(server, "A", 3)
    done = keys_of(server, who)[0]
    real = server.adapter.bindings
    server.adapter.bindings = replace(
        real,
        select=lambda grant, observed: tuple(
            c for c in real.select(grant, observed) if c.job.canonical_key != done
        ),
    )
    _, first = await emission(server, who)
    assert hinted(first) == keys_of(server, who)[1:2]  # nosec B101 - pytest assertion
    assert states(server)[done] == "PENDING"  # nosec B101 - pytest assertion
    server.adapter.bindings = replace(real, render=lambda *args: None)
    value, result = await emission(server, who)
    assert result is value  # nosec B101 - pytest assertion
    assert sorted(states(server).values()) == ["EMITTED", "PENDING", "PENDING"]  # nosec B101 - pytest assertion
    server.adapter.bindings = real
    _, last = await emission(server, who)
    assert done in hinted(last)  # nosec B101 - pytest assertion
    await server.workers.close()


@pytest.mark.timeout(600)
@pytest.mark.parametrize("calls", [2, 8])
@in_loop
async def test_concurrent_calls_hint_each_job_exactly_once(tmp_path, calls):
    """100 rounds; each job EMITTED once, and only when in a returned hint."""
    server = None
    for round_ in range(100):
        if round_ % 30 == 0:
            if server is not None:
                await server.workers.close()
            carrier = HintCarrier.META if round_ % 60 else HintCarrier.TEXT
            server = E2Server(tmp_path / f"phase-{round_}", carrier=carrier)
            server.adapter = server.build_adapter(enabled=True)
        who, _ = await allocate(server, f"chat-{round_}", 3)
        results = await asyncio.gather(*(emission(server, who) for _ in range(calls)))
        seen = Counter(key for _, result in results for key in hinted(result))
        emitted = {k for k, v in states(server, who).items() if v == "EMITTED"}
        assert set(seen) == emitted and set(seen.values()) <= {1}  # nosec B101 - pytest assertion
        assert len(emitted) == min(3, 2 * calls)  # nosec B101 - pytest assertion
    assert server is not None  # nosec B101 - pytest assertion
    await server.workers.close()


POINTS = ("after_reserve", "after_adapt", "after_validation", "before_commit")


@pytest.mark.parametrize("point", POINTS)
@in_loop
async def test_cancel_at_each_pause_point_aborts_and_never_rehints(tmp_path, point):
    server = E2Server(tmp_path / "phase")
    who, _ = await allocate(server, "A", 2)
    entered, release = asyncio.Event(), asyncio.Event()

    async def pause(name):
        if name == point:
            entered.set()
            await release.wait()

    task = asyncio.ensure_future(emission(server, who, checkpoint=pause))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert set(states(server).values()) == {"ABORTED"}  # nosec B101 - pytest assertion
    value, result = await emission(server, who)
    assert result is value  # nosec B101 - pytest assertion
    await server.workers.close()


@pytest.mark.parametrize("step", ["emit", "reset"])
@in_loop
async def test_commit_rowcount_mismatch_returns_original_and_aborts(tmp_path, step):
    """A bypassing writer changes one reserved row before the commit."""
    server = E2Server(tmp_path / "phase")
    who, _ = await allocate(server, "A", 2)
    keys = keys_of(server, who)
    real = server.adapter.bindings
    if step == "reset":
        server.adapter.bindings = replace(
            real, select=lambda grant, observed: real.select(grant, observed)[:1]
        )
    victim = keys[0 if step == "emit" else 1]

    async def tamper(name):
        if name == "before_commit":
            db = sqlite3.connect(server.lab.ledger.path)
            db.execute(
                "UPDATE emit SET reservation_id=? WHERE jobref=?", ("f" * 32, victim)
            )
            db.commit()
            db.close()

    value, result = await emission(server, who, checkpoint=tamper)
    assert result is value  # nosec B101 - pytest assertion
    after = states(server)
    assert after[victim] == "RESERVED"  # nosec B101 - pytest assertion
    assert {after[k] for k in keys if k != victim} == {"ABORTED"}  # nosec B101 - pytest assertion
    server.adapter.bindings = real
    value, result = await emission(server, who)
    assert result is value  # nosec B101 - pytest assertion
    await server.workers.close()


@in_loop
async def test_two_keys_interleaved_never_cross(tmp_path):
    server = E2Server(tmp_path / "phase")
    a, _ = await allocate(server, "A", 2)
    b, _ = await allocate(server, "B", 2)
    own = {a: set(keys_of(server, a)), b: set(keys_of(server, b))}
    order = (a, b, a, b)
    for _ in range(32):  # a busy worker or store returns the original; retry
        if "PENDING" not in states(server).values():
            break
        results = await asyncio.gather(*(emission(server, who) for who in order))
        for who, (_, result) in zip(order, results, strict=True):
            assert set(hinted(result)) <= own[who]  # nosec B101 - pytest assertion
    assert set(states(server).values()) == {"EMITTED"}  # nosec B101 - pytest assertion
    await server.workers.close()


def test_guard_negative_control_rendered_subset():
    """Removing the rendered-within-route guard must break a routed test."""
    from tests.contracts.job_awareness import test_hint_routed

    def permissive(self, candidates, jobs):
        return tuple(candidate.job for candidate in candidates)

    real = HintAdapter._rendered
    HintAdapter._rendered = permissive
    try:
        with pytest.raises(AssertionError):
            test_hint_routed.test_unsafe_candidates_or_render_suppress("outside_route")
    finally:
        HintAdapter._rendered = real
