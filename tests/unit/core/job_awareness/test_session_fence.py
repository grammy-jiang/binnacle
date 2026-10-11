"""E2 S2: per-key asyncio fence; timed-out or cancelled waiters never hold it."""

import asyncio

import pytest

from binnacle.features.commands.job_awareness.session_fence import (
    FenceSet,
    _abandon,
    acquire,
)


def test_acquire_free_and_timeout_without_leak():
    async def scenario():
        lock = asyncio.Lock()
        assert await acquire(lock, 0.05) is True
        assert await acquire(lock, 0.01) is False
        lock.release()
        await asyncio.sleep(0)
        assert not lock.locked()  # the timed-out waiter did not keep it

    asyncio.run(scenario())


def test_cancelled_waiter_never_keeps_the_lock():
    async def scenario():
        lock = asyncio.Lock()
        await lock.acquire()
        waiter = asyncio.ensure_future(acquire(lock, 5.0))
        await asyncio.sleep(0.01)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        lock.release()
        for _ in range(3):
            await asyncio.sleep(0)
        assert not lock.locked()

    asyncio.run(scenario())


def test_abandoning_an_acquired_task_releases_it():
    async def scenario():
        lock = asyncio.Lock()
        task = asyncio.ensure_future(lock.acquire())
        await task
        assert lock.locked()
        _abandon(task, lock)
        await asyncio.sleep(0)
        assert not lock.locked()

    asyncio.run(scenario())


def test_fence_set_is_per_key_and_reports_timeouts():
    async def scenario():
        fences = FenceSet(0.01)
        assert fences.lock("a") is fences.lock("a")
        assert fences.lock("a") is not fences.lock("b")
        async with fences.hold("a") as outer:
            assert outer is True
            async with fences.hold("a") as inner:
                assert inner is False
            async with fences.hold("b") as other:
                assert other is True
        assert not fences.lock("a").locked()

    asyncio.run(scenario())
