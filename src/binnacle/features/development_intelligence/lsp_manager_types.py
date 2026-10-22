"""P2.6 private Provider Manager state; no protocol or MCP dependencies."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .lsp_workspace_access import AuthorizedWorkspace

InstanceState = Literal["starting", "ready", "stopping", "failed"]
InstanceKey = tuple[Path, tuple[int, int], str]


class ProviderManagerError(RuntimeError):
    """Sanitized private manager failure; never include user paths or LSP wire."""


@dataclass(frozen=True)
class InstanceObservation:
    """Private local process evidence. Does not certify sandbox confinement."""

    state: InstanceState
    active_requests: int
    workspace_identity: tuple[int, int]
    is_stopped: bool
    cleanup_unverified: bool


@dataclass(frozen=True)
class ShutdownObservation:
    """Bounded manager close outcome. No assumption of unobserved descendants."""

    instances_requested: int
    instances_stopped: int
    requests_cancelled: int
    cleanup_unverified: bool


@dataclass
class ManagedProvider:
    """Exactly one P2.4 owner/one P2.5 document state per workspace/profile."""

    key: InstanceKey
    workspace: AuthorizedWorkspace
    owner: Any
    state: InstanceState = "starting"
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    worker: asyncio.Task[None] | None = None
    documents: Any | None = None
    slots: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))
    users: int = 0
    touched: float = field(default_factory=time.monotonic)
    error: str | None = None
    fatal: bool = False
    aborted: bool = False

    @property
    def idle(self) -> bool:
        return self.users == 0


@dataclass(frozen=True)
class Cooldown:
    until: float
    failures: int
    reason: str
    fatal: bool = False
