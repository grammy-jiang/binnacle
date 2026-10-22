"""Bounded private LSP provider cooldown bookkeeping (no processes or wire)."""

from __future__ import annotations

from .lsp_manager_types import Cooldown, InstanceKey, ManagedProvider

_MAX_KEYS = 128


def record_failure(
    registry: dict[InstanceKey, Cooldown],
    entry: ManagedProvider,
    *,
    now: float,
    base_seconds: float,
    max_seconds: float,
) -> None:
    """Exponential backoff without retaining unbounded unrelated workspaces.

    Keep the current key's expired record across consecutive failed restarts;
    otherwise backoff would reset to its first step on every retry.
    """
    for key, older in tuple(registry.items()):
        if key != entry.key and older.until <= now:
            registry.pop(key, None)
    if len(registry) >= _MAX_KEYS and entry.key not in registry:
        oldest = min(registry, key=lambda key: registry[key].until)
        registry.pop(oldest)
    previous = registry.get(entry.key)
    failures = previous.failures + 1 if previous else 1
    reason = entry.error or "provider_unavailable"
    if entry.fatal:
        registry[entry.key] = Cooldown(float("inf"), failures, reason, True)
    else:
        delay = min(max_seconds, base_seconds * 2 ** min(failures - 1, 16))
        registry[entry.key] = Cooldown(now + delay, failures, reason)
