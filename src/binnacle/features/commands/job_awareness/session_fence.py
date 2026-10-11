"""Per-key asyncio fence for the E2 lab (design §2.6). LAB_ONLY.

One ``asyncio.Lock`` per ``kd`` on the server event loop. Emission, RETIRE,
grant replacement, allocation and SUSPEND hold it for their whole duration.
Acquisition waits at most ``timeout_s``; a timed-out or cancelled waiter never
keeps the lock, including when acquisition races with the timeout.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


def _abandon(task: "asyncio.Future[bool]", lock: asyncio.Lock) -> None:
    """Cancel a pending acquire; release it if it already succeeded."""

    def release(done: "asyncio.Future[bool]") -> None:
        if not done.cancelled() and done.exception() is None and done.result():
            lock.release()

    task.add_done_callback(release)
    task.cancel()


async def acquire(lock: asyncio.Lock, timeout_s: float) -> bool:
    task: asyncio.Future[bool] = asyncio.ensure_future(lock.acquire())
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout_s)
    except BaseException:
        _abandon(task, lock)
        raise
    if task in done:
        return task.result()
    _abandon(task, lock)
    return False


class FenceSet:
    """kd -> asyncio.Lock. Locks are created lazily on the running loop."""

    def __init__(self, timeout_s: float) -> None:
        self.timeout_s = timeout_s
        self._locks: dict[str, asyncio.Lock] = {}

    def lock(self, kd: str) -> asyncio.Lock:
        lock = self._locks.get(kd)
        if lock is None:
            lock = self._locks[kd] = asyncio.Lock()
        return lock

    @asynccontextmanager
    async def hold(self, kd: str) -> AsyncIterator[bool]:
        """Yield True while the fence is held; False after a timeout."""
        lock = self.lock(kd)
        held = await acquire(lock, self.timeout_s)
        try:
            yield held
        finally:
            if held:
                lock.release()
