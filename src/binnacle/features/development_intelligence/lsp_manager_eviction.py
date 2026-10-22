"""P2.6 private idle-process health and eviction sweep.

No process signaling occurs here. P2.4 owner remains cleanup authority.
"""

from __future__ import annotations

import asyncio
from typing import Any


async def sweep_idle(manager: Any) -> None:
    """Evict unused providers and detect a dead process without starting any."""
    try:
        interval = max(0.05, min(manager._settings.idle_timeout_s / 3, 2.0))
        while not manager._closing:
            await asyncio.sleep(interval)
            now = asyncio.get_running_loop().time()
            async with manager._lock:
                for entry in manager._entries.values():
                    if entry.state != "ready":
                        continue
                    # The P2.4 process owner publishes a read-only liveness
                    # witness; no client-provided PID or process signaling.
                    if not getattr(entry.owner, "process_running", True):
                        entry.error = "provider_crashed_while_idle"
                        entry.state = "stopping"
                        entry.stop.set()
                    elif (
                        entry.idle
                        and now - entry.touched >= manager._settings.idle_timeout_s
                    ):
                        entry.state = "stopping"
                        entry.stop.set()
    except asyncio.CancelledError:
        pass
    except Exception:  # noqa: BLE001 - unknown liveness must fail closed
        # A silently dead sweeper would leave crashed providers resident for
        # the rest of this service generation. Refuse new launches instead.
        async with manager._lock:
            manager._unsafe_cleanup = True
            for item in manager._entries.values():
                item.fatal = True
                item.error = "provider_sweep_unverified"
                item.state = "stopping"
                item.stop.set()
