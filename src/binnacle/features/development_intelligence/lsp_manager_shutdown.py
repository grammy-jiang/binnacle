"""P2.6 cancellation-shielded, bounded manager shutdown implementation.

The P2.4 process owner remains the only authority to signal subprocesses.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .lsp_manager_types import ShutdownObservation


async def finish_manager_close(manager: Any) -> ShutdownObservation:
    """Drain active requests, stop providers, return truthful cleanup evidence."""
    try:
        sweeper = manager._sweeper
        if sweeper is not None:
            sweeper.cancel()
            await asyncio.gather(sweeper, return_exceptions=True)
        async with manager._lock:
            entries = tuple(manager._entries.values())
            callers = tuple(
                task for task in manager._callers if task is not asyncio.current_task()
            )
        cancelled = 0
        if callers:
            _, lingering = await asyncio.wait(
                callers, timeout=manager._shutdown_timeout / 2
            )
            if lingering:
                cancelled = len(lingering)
                for task in lingering:
                    task.cancel()
                await asyncio.wait(lingering, timeout=manager._shutdown_timeout / 2)
        for entry in entries:
            entry.state = "stopping"
            entry.stop.set()
        tasks = [entry.worker for entry in entries if entry.worker is not None]
        if tasks:
            _, lingering_workers = await asyncio.wait(
                tasks, timeout=manager._shutdown_timeout
            )
            for worker in lingering_workers:
                worker.cancel()
            if lingering_workers:
                await asyncio.wait(lingering_workers, timeout=manager._shutdown_timeout)
        manager._closed = True
        unverified = (
            manager._unsafe_cleanup
            or any(not item.finished.is_set() or item.fatal for item in entries)
            or any(item.cleanup_unverified for item in manager._history)
        )
        manager._shutdown = ShutdownObservation(
            instances_requested=len(entries),
            instances_stopped=sum(item.finished.is_set() for item in entries),
            requests_cancelled=cancelled,
            cleanup_unverified=unverified,
        )
        return manager._shutdown
    finally:
        manager._closed = True


async def abort_cold_start(entry: Any, seconds: float) -> None:
    """Request bounded P2.4 startup abort without cancelling owner cleanup.

    The worker still exclusively enters/exits the provider session. P2.4
    aclose is its supported external stop request during initialization.
    """
    from .lsp_manager_types import ProviderManagerError

    try:
        await asyncio.wait_for(asyncio.shield(entry.owner.aclose()), seconds)
    except asyncio.CancelledError:
        entry.fatal = True
        entry.error = "provider_cleanup_unverified"
        raise
    except Exception as exc:
        entry.fatal = True
        entry.error = "provider_cleanup_unverified"
        raise ProviderManagerError("provider_cleanup_unverified") from exc
