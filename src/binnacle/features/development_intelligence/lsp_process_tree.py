"""P2.4 native POSIX observations of an owned LSP process tree.

Only PIDs observed as descendants or members of an independently launched
provider's own session are eligible for cleanup. Never signal a PID supplied
by a client, trace, or unverified source. This is not an OS sandbox and cannot
prove absence of children that have escaped all observable ownership.

Optional psutil is imported on use, not during Binnacle's mandatory startup.
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    created: float
    pgid: int


@dataclass(frozen=True)
class ProcessCleanup:
    status: Literal["observed_clean", "cleanup_unverified"]
    root_pid: int | None
    observed_descendants: int
    escaped_descendants: int
    remaining: tuple[int, ...]
    reason: str


class NativeProviderTree:
    """Observe and clean exactly one privately launched POSIX process group."""

    def __init__(self, *, grace_seconds: float = 0.4, kill_seconds: float = 1.0):
        if os.name != "posix":
            raise RuntimeError("lsp_process_owner_requires_posix")
        if not 0 < grace_seconds <= 5 or not 0 < kill_seconds <= 5:
            raise ValueError("invalid_lsp_process_cleanup_deadline")
        self.grace_seconds = grace_seconds
        self.kill_seconds = kill_seconds
        self.root: ProcessIdentity | None = None
        self.members: dict[int, ProcessIdentity] = {}
        self.escaped: set[int] = set()
        self._ended = False

    @staticmethod
    def _identity(pid: int) -> ProcessIdentity | None:
        import psutil

        try:
            proc = psutil.Process(pid)
            if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                return None
            return ProcessIdentity(pid, proc.create_time(), os.getpgid(pid))
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            ProcessLookupError,
            PermissionError,
        ):
            return None

    @classmethod
    def _matches(cls, identity: ProcessIdentity) -> bool:
        observed = cls._identity(identity.pid)
        return observed is not None and abs(observed.created - identity.created) < 0.001

    def capture(self, pid: int) -> None:
        if self.root is not None or self._ended:
            raise RuntimeError("lsp_process_owner_already_used")
        if type(pid) is not int or pid <= 1:
            raise ValueError("invalid_owned_lsp_pid")
        identity = self._identity(pid)
        if identity is None or identity.pgid != pid:
            raise RuntimeError("lsp_process_missing_independent_session")
        self.root = identity
        self.members[pid] = identity

    def observe(self) -> None:
        """Sample descendants and all members of this *verified* session.

        The root can exit before its children. The already captured PGID is
        preserved, but every signal is still constrained by PID+create_time.
        """
        if self.root is None or self._ended:
            return
        import psutil

        root = self.root
        if self._matches(root):
            try:
                children = psutil.Process(root.pid).children(recursive=True)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                children = []
            for child in children:
                identity = self._identity(child.pid)
                if identity is None:
                    continue
                self.members[identity.pid] = identity
                if identity.pgid != root.pgid:
                    self.escaped.add(identity.pid)
        # A previously observed descendant may call setsid() after its first
        # sample. Recheck its current group, not only at discovery, so a
        # later escape cannot be misreported as ordinary group cleanup.
        for previous in tuple(self.members.values()):
            if previous.pid == root.pid:
                continue
            current = self._identity(previous.pid)
            if (
                current is not None
                and abs(current.created - previous.created) < 0.001
                and current.pgid != root.pgid
            ):
                self.escaped.add(previous.pid)
        # Covers same-process-group descendants even after their parent exits.
        for proc in psutil.process_iter(attrs=["pid"]):
            pid = proc.info["pid"]
            if pid in self.members:
                continue
            identity = self._identity(pid)
            if identity is not None and identity.pgid == root.pgid:
                self.members[pid] = identity

    def _alive(self) -> list[ProcessIdentity]:
        return [
            identity for identity in self.members.values() if self._matches(identity)
        ]

    @classmethod
    def _signal(cls, identity: ProcessIdentity, sig: signal.Signals) -> None:
        import psutil

        if not cls._matches(identity):
            return
        try:
            process = psutil.Process(identity.pid)
            if abs(process.create_time() - identity.created) < 0.001:
                process.send_signal(sig)
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            ProcessLookupError,
            PermissionError,
        ):
            pass

    async def _settle(self, deadline: float) -> None:
        while time.monotonic() < deadline:
            self.observe()
            if not self._alive():
                return
            await asyncio.sleep(min(0.05, max(0, deadline - time.monotonic())))

    async def cleanup(self) -> ProcessCleanup:
        """Clean observed members and describe uncertainty, never infer sandboxing."""
        if self._ended:
            raise RuntimeError("lsp_process_cleanup_already_called")
        if self.root is None:
            self._ended = True
            return ProcessCleanup(
                "cleanup_unverified", None, 0, 0, (), "root_not_observed"
            )
        self.observe()
        root = self.root
        for identity in self._alive():
            self._signal(identity, signal.SIGTERM)
        await self._settle(time.monotonic() + self.grace_seconds)
        for identity in self._alive():
            self._signal(identity, signal.SIGKILL)
        await self._settle(time.monotonic() + self.kill_seconds)
        self.observe()
        remaining = tuple(sorted(identity.pid for identity in self._alive()))
        self._ended = True
        if self.escaped:
            reason = "escaped_descendant_observed"
        elif remaining:
            reason = "owned_process_still_alive"
        else:
            reason = "observed_processes_reaped"
        status = "cleanup_unverified" if self.escaped or remaining else "observed_clean"
        return ProcessCleanup(
            status=status,
            root_pid=root.pid,
            observed_descendants=len(self.members) - 1,
            escaped_descendants=len(self.escaped),
            remaining=remaining,
            reason=reason,
        )
