"""E2 S4 / CA-2 under concurrency: once-only emission around adapt_routed.

``EmitLedger`` is a test double of the S2 lab ``emit`` table with the exact
design §2.6 reserve/emit/reset/abort SQL and rowcount rules. These tests pin
the adapter side of the contract: a job becomes EMITTED only when it appears
in a returned hint, a hint names only jobs that its own reservation holds,
and every job is hinted at most once, with or without the per-key fence.
"""

import asyncio
from collections import Counter
from dataclasses import replace

import pytest

from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.mcp.job_awareness_hint import META_KEY, HintAdapter
from tests.contracts.job_awareness.routed_support import (
    EmitLedger,
    RoutedLab,
    emission,
    yield_,
)
from tests.contracts.job_awareness.synthetic_app import in_loop

KD = "e" * 32 + ":" + "a" * 32 + ":" + "b" * 32


def hinted(result) -> list[str]:
    meta = result.meta or {}
    text = meta.get(META_KEY)
    if text is None and len(result.content) > 1:
        text = result.content[-1].text
    if text is None:
        return []
    body = text.removeprefix("[Binnacle job reminder] ")
    return [part.split(" ")[0] for part in body.split("; ")]


def ordered_keys(jobs) -> list[str]:
    return sorted(job.canonical_key for job in jobs)


@pytest.mark.parametrize("live", [3, 4, 8])
@in_loop
async def test_live_jobs_are_hinted_two_per_call_in_order(live):
    with RoutedLab(8) as lab:
        adapter = lab.routed(enabled=True)
        ledger = EmitLedger(KD, lab.jobs[:live])
        keys = ordered_keys(lab.jobs[:live])
        for start in range(0, live, 2):
            result = await emission(lab, adapter, ledger)
            assert hinted(result) == keys[start : start + 2]  # nosec B101 - pytest assertion
        assert hinted(await emission(lab, adapter, ledger)) == []  # nosec B101 - pytest assertion
        assert {ledger.state(job) for job in lab.jobs[:live]} == {"EMITTED"}  # nosec B101 - pytest assertion


@in_loop
async def test_fewer_than_two_candidates_reserve_only_those():
    with RoutedLab(1) as lab:
        adapter = lab.routed(enabled=True)
        ledger = EmitLedger(KD, lab.jobs)
        assert hinted(await emission(lab, adapter, ledger)) == ordered_keys(lab.jobs)  # nosec B101 - pytest assertion


@in_loop
async def test_unselected_jobs_are_reset_not_blocked():
    """A COMPLETE/expired job is not rendered, returns to PENDING, blocks nothing."""
    with RoutedLab(3) as lab:
        adapter = lab.routed(enabled=True)
        done = min(lab.jobs, key=lambda job: job.canonical_key)
        select = adapter.bindings.select
        adapter.bindings = replace(
            adapter.bindings,
            select=lambda grant, observed: tuple(
                c for c in select(grant, observed) if c.job != done
            ),
        )
        ledger = EmitLedger(KD, lab.jobs)
        first = hinted(await emission(lab, adapter, ledger))
        assert done.canonical_key not in first and len(first) == 1  # nosec B101 - pytest assertion
        assert ledger.state(done) == "PENDING"  # nosec B101 - pytest assertion
        second = hinted(await emission(lab, adapter, ledger))
        assert len(second) == 1 and set(first).isdisjoint(second)  # nosec B101 - pytest assertion
        assert ledger.state(done) == "PENDING"  # nosec B101 - pytest assertion


@in_loop
async def test_render_none_resets_every_reserved_job():
    with RoutedLab(2) as lab:
        adapter = lab.routed(enabled=True)
        real = adapter.bindings
        adapter.bindings = replace(real, render=lambda *args: None)
        ledger = EmitLedger(KD, lab.jobs)
        assert hinted(await emission(lab, adapter, ledger)) == []  # nosec B101 - pytest assertion
        assert {ledger.state(job) for job in lab.jobs} == {"PENDING"}  # nosec B101 - pytest assertion
        adapter.bindings = real
        assert hinted(await emission(lab, adapter, ledger)) == ordered_keys(lab.jobs)  # nosec B101 - pytest assertion


async def drain(lab, adapter, ledger, calls, *, fenced):
    """Run batches of concurrent calls until no job is PENDING."""
    lock = asyncio.Lock()

    async def one():
        if fenced:
            async with lock:
                return await emission(lab, adapter, ledger)
        return await emission(lab, adapter, ledger, fence=yield_)

    results = []
    for _ in range(64):
        if not any(ledger.state(job) == "PENDING" for job in ledger.jobs):
            break
        results.extend(await asyncio.gather(*(one() for _ in range(calls))))
    return results


@pytest.mark.parametrize("fenced", [True, False])
@pytest.mark.parametrize("calls", [2, 8])
@in_loop
async def test_concurrent_calls_hint_each_job_exactly_once(calls, fenced):
    with RoutedLab(8) as lab:
        # 100 rounds on the design path (fenced); 50 extra unfenced rounds
        # show that the reserve CAS alone keeps emission once-only.
        for round_ in range(100 if fenced else 50):
            carrier = HintCarrier.META if round_ % 2 else HintCarrier.TEXT
            adapter = lab.routed(enabled=True, carrier=carrier)
            ledger = EmitLedger(KD, lab.jobs)
            results = await drain(lab, adapter, ledger, calls, fenced=fenced)
            seen = Counter(key for result in results for key in hinted(result))
            emitted = {
                job.canonical_key for job in lab.jobs if ledger.state(job) == "EMITTED"
            }
            assert set(seen) == emitted  # nosec B101 - pytest assertion
            assert set(seen.values()) == {1}, seen  # nosec B101 - pytest assertion
            assert all(len(hinted(result)) <= 2 for result in results)  # nosec B101 - pytest assertion
            assert ledger.counts() == {"EMITTED": 8}  # nosec B101 - pytest assertion


class Gate:
    """Pause inside the routed call; the test cancels or retires meanwhile."""

    def __init__(self):
        self.entered, self.release = asyncio.Event(), asyncio.Event()

    async def __call__(self, _=0):
        self.entered.set()
        await self.release.wait()


@in_loop
async def test_cancel_at_the_pause_point_aborts_and_never_rehints():
    with RoutedLab(2) as lab:
        adapter = lab.routed(enabled=True)
        ledger = EmitLedger(KD, lab.jobs)
        gate = Gate()
        task = asyncio.ensure_future(emission(lab, adapter, ledger, fence=gate))
        await gate.entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert {ledger.state(job) for job in lab.jobs} == {"ABORTED"}  # nosec B101 - pytest assertion
        assert hinted(await emission(lab, adapter, ledger)) == []  # nosec B101 - pytest assertion


@in_loop
async def test_cancel_inside_the_worker_returns_no_result():
    with RoutedLab(2) as lab:
        adapter = lab.routed(enabled=True)
        ledger = EmitLedger(KD, lab.jobs)
        entered, release = asyncio.Event(), asyncio.Event()
        loop = asyncio.get_running_loop()
        real = adapter.bindings.select

        def slow(grant, observed):
            loop.call_soon_threadsafe(entered.set)
            asyncio.run_coroutine_threadsafe(release.wait(), loop).result(5)
            return real(grant, observed)

        adapter.bindings = replace(adapter.bindings, select=slow)
        task = asyncio.ensure_future(emission(lab, adapter, ledger))
        await entered.wait()
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await adapter.workers.close()  # drain the worker before the loop ends
        assert {ledger.state(job) for job in lab.jobs} == {"ABORTED"}  # nosec B101 - pytest assertion


@pytest.mark.parametrize("step", ["emit", "reset"])
@in_loop
async def test_commit_rowcount_mismatch_returns_original_and_aborts(step):
    with RoutedLab(3) as lab:
        adapter = lab.routed(enabled=True)
        ledger = EmitLedger(KD, lab.jobs[:2] if step == "emit" else lab.jobs)
        select = adapter.bindings.select
        if step == "reset":
            adapter.bindings = replace(
                adapter.bindings,
                select=lambda grant, observed: select(grant, observed)[:1],
            )
        gate = Gate()
        task = asyncio.ensure_future(emission(lab, adapter, ledger, fence=gate))
        await gate.entered.wait()
        # A bypassing writer (no fence) changes one reserved row underneath.
        reserved = sorted(ledger.jobs, key=lambda job: job.canonical_key)[:2]
        victim = reserved[0 if step == "emit" else 1]
        ledger.db.execute(
            "UPDATE emit SET reservation_id=? WHERE jobref=?",
            ("f" * 32, victim.canonical_key),
        )
        gate.release.set()
        result = await task
        assert hinted(result) == []  # nosec B101 - pytest assertion
        assert ledger.state(victim) == "RESERVED"  # nosec B101 - pytest assertion
        others = [job for job in reserved if job != victim]
        assert {ledger.state(job) for job in others} == {"ABORTED"}  # nosec B101 - pytest assertion
        # A stuck RESERVED row is never re-hintable.
        later = hinted(await emission(lab, adapter, ledger))
        assert victim.canonical_key not in later  # nosec B101 - pytest assertion


@in_loop
async def test_two_keys_interleaved_never_cross():
    with RoutedLab(4) as lab:
        adapter = lab.routed(enabled=True)
        left = EmitLedger("a" * 98, lab.jobs[:2])
        right = EmitLedger("b" * 98, lab.jobs[2:])
        ledgers = (left, right, left, right)
        for _ in range(32):  # a busy worker returns the original; retry
            if "PENDING" not in left.counts() | right.counts():
                break
            results = await asyncio.gather(
                *(emission(lab, adapter, ledger, fence=yield_) for ledger in ledgers)
            )
            for ledger, result in zip(ledgers, results, strict=True):
                own = {job.canonical_key for job in ledger.jobs}
                assert set(hinted(result)) <= own  # nosec B101 - pytest assertion
        for ledger in (left, right):
            assert {ledger.state(job) for job in ledger.jobs} == {"EMITTED"}  # nosec B101 - pytest assertion


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
