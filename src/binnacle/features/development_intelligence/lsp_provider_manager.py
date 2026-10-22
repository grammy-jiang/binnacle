"""P2.6 private, bounded, lifespan-owned provider registry.

One resident P2.4 owner + P2.5 document session per canonical workspace and
trusted profile. This module does not create LSP adapters, JSON-RPC, new MCP
tools or a process sandbox. P2.7 owns any eventual FastMCP lifespan mount.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from typing_extensions import Self

from binnacle.config import RootsSettings
from binnacle.config_development_intelligence import DevelopmentIntelligenceSettings

from .lsp_document_sync import AuthorizedDocumentSession
from .lsp_manager_cooldown import record_failure
from .lsp_manager_types import (
    Cooldown,
    InstanceKey,
    InstanceObservation,
    ManagedProvider,
    ProviderManagerError,
    ShutdownObservation,
)
from .lsp_process_owner import PrivatePyrightProcessOwner
from .lsp_workspace_access import AuthorizedWorkspace


class PrivateProviderManager:
    """Explicit opt-in, per-service-generation, lazy Pyright provider manager.

    Client admission, not MCP tools, is its boundary. Calls sharing a Git
    worktree use the same provider; document operations remain serialized by
    P2.5. A failed/uncertain lifetime is never implicitly reused.
    """

    def __init__(
        self,
        feature_settings: DevelopmentIntelligenceSettings,
        roots_settings: RootsSettings,
        *,
        startup_timeout_s: float = 20.0,
        queue_timeout_s: float = 5.0,
        shutdown_timeout_s: float = 8.0,
        cooldown_base_s: float = 1.0,
        cooldown_max_s: float = 60.0,
        max_pending_requests: int = 32,
        max_parallel_requests: int = 4,
        max_per_provider_requests: int = 2,
        _owner_factory: Callable[..., Any] = PrivatePyrightProcessOwner,
        _document_factory: Callable[..., Any] = AuthorizedDocumentSession,
    ) -> None:
        for name, value, ceiling in (
            ("startup", startup_timeout_s, 120),
            ("queue", queue_timeout_s, 120),
            ("shutdown", shutdown_timeout_s, 120),
            ("cooldown_base", cooldown_base_s, 300),
            ("cooldown_max", cooldown_max_s, 3600),
        ):
            if type(value) not in (int, float) or not 0 < value <= ceiling:
                raise ValueError(f"invalid_provider_manager_{name}_deadline")
        if cooldown_max_s < cooldown_base_s:
            raise ValueError("invalid_provider_cooldown_range")
        for name, value, ceiling in (
            ("pending", max_pending_requests, 256),
            ("parallel", max_parallel_requests, 32),
            ("per_provider", max_per_provider_requests, 32),
        ):
            if type(value) is not int or not 0 < value <= ceiling:
                raise ValueError(f"invalid_provider_manager_{name}_limit")
        # Deep-copy mutable Pydantic models. They are host authority, not
        # agent/session controlled; a later settings change needs a new manager.
        self._settings = feature_settings.model_copy(deep=True)
        self._allowed_roots = tuple(roots_settings.canonical_allowed)
        self._owner_factory = _owner_factory
        self._document_factory = _document_factory
        self._profile_hash = self._profile_fingerprint()
        self._startup_timeout = float(startup_timeout_s)
        self._queue_timeout = float(queue_timeout_s)
        self._shutdown_timeout = float(shutdown_timeout_s)
        self._cooldown_base = float(cooldown_base_s)
        self._cooldown_max = float(cooldown_max_s)
        self._max_pending = max_pending_requests
        self._max_per_provider = max_per_provider_requests
        self._parallel_slots = asyncio.Semaphore(max_parallel_requests)
        self._entries: dict[InstanceKey, ManagedProvider] = {}
        self._cooldowns: dict[InstanceKey, Cooldown] = {}
        self._lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._close_task: asyncio.Task[ShutdownObservation] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closing = False
        self._closed = False
        self._unsafe_cleanup = False
        self._outstanding = 0
        self._callers: set[asyncio.Task[Any]] = set()
        self._sweeper: asyncio.Task[None] | None = None
        self._history: deque[InstanceObservation] = deque(maxlen=64)
        self._shutdown: ShutdownObservation | None = None

    def _profile_fingerprint(self) -> str:
        profile = self._settings.profiles.get("pyright")
        if profile is None:
            return "disabled"
        return hashlib.sha256(profile.model_dump_json().encode("utf-8")).hexdigest()

    @property
    def closed(self) -> bool:
        return self._closing or self._closed

    @property
    def resident_count(self) -> int:
        return len(self._entries)

    @property
    def pending_count(self) -> int:
        return self._outstanding

    def observations(self) -> tuple[InstanceObservation, ...]:
        return tuple(self._history) + tuple(
            InstanceObservation(
                state=entry.state,
                active_requests=entry.users,
                workspace_identity=entry.key[1],
                is_stopped=entry.finished.is_set(),
                cleanup_unverified=entry.fatal,
            )
            for entry in self._entries.values()
        )

    def _assert_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise ProviderManagerError("provider_manager_event_loop_mismatch")

    async def __aenter__(self) -> Self:
        self._assert_loop()
        if self.closed:
            raise ProviderManagerError("provider_manager_already_closed")
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        await self.aclose()

    def _key(self, workspace: AuthorizedWorkspace) -> InstanceKey:
        return workspace.workspace_root, workspace.root_identity, self._profile_hash

    def _record_failure(self, entry: ManagedProvider) -> None:
        record_failure(
            self._cooldowns,
            entry,
            now=asyncio.get_running_loop().time(),
            base_seconds=self._cooldown_base,
            max_seconds=self._cooldown_max,
        )

    async def _run_entry(self, entry: ManagedProvider) -> None:
        """The ONLY asyncio task that enters/leaves this P2.4 owner lifespan."""
        try:
            async with entry.owner.session() as server:  # noqa: SIM117 - document factory needs server
                async with self._document_factory(
                    server,
                    entry.workspace,
                    request_timeout_s=self._settings.request_timeout_s,
                ) as documents:
                    async with self._lock:
                        if not self._closing and not entry.stop.is_set():
                            entry.documents = documents
                            entry.state = "ready"
                        else:
                            entry.state = "stopping"
                        entry.ready.set()
                    await entry.stop.wait()
        except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 - lifecycle fail-closed
            entry.state = "stopping"
            entry.stop.set()
            if entry.error is None and not self._closing:
                entry.error = "provider_start_or_runtime_failure"
            if "cleanup_unverified" in str(exc):
                entry.fatal = True
        finally:
            try:
                await entry.owner.aclose()
            except (Exception, asyncio.CancelledError):  # noqa: BLE001 - cleanup audit
                entry.fatal = True
                entry.error = "provider_cleanup_unverified"
            exit_evidence = getattr(entry.owner, "last_exit", None)
            if exit_evidence is not None and exit_evidence.cleanup_unverified:
                entry.fatal = True
                entry.error = "provider_cleanup_unverified"
            entry.documents = None
            entry.ready.set()
            async with self._lock:
                if self._entries.get(entry.key) is entry:
                    del self._entries[entry.key]
                if entry.fatal:
                    # Unverified descendants could affect other workspaces.
                    # Stop all resident providers and block all future launches
                    # until an entirely new service generation is authorized.
                    self._unsafe_cleanup = True
                    for other in self._entries.values():
                        other.state = "stopping"
                        other.stop.set()
                if (
                    entry.error is not None
                    and not self._closing
                    and (not entry.aborted or entry.fatal)
                ):
                    entry.state = "failed"
                    self._record_failure(entry)
                else:
                    entry.state = "stopping"
                self._history.append(
                    InstanceObservation(
                        state=entry.state,
                        active_requests=entry.users,
                        workspace_identity=entry.key[1],
                        is_stopped=True,
                        cleanup_unverified=entry.fatal,
                    )
                )
                entry.finished.set()

    async def _reserve(self, workspace: AuthorizedWorkspace) -> ManagedProvider:
        key = self._key(workspace)
        while True:
            eviction: asyncio.Task[None] | None = None
            async with self._lock:
                if self._closing:
                    raise ProviderManagerError("provider_manager_closing")
                if self._unsafe_cleanup:
                    raise ProviderManagerError("provider_cleanup_unverified")
                cooldown = self._cooldowns.get(key)
                if (
                    cooldown is not None
                    and cooldown.until > asyncio.get_running_loop().time()
                ):
                    raise ProviderManagerError(
                        "provider_cleanup_unverified"
                        if cooldown.fatal
                        else "provider_cooldown"
                    )
                entry = self._entries.get(key)
                if entry is not None:
                    if entry.state == "stopping":
                        raise ProviderManagerError("provider_instance_stopping")
                    entry.users += 1
                    return entry
                if len(self._entries) >= self._settings.max_resident_servers:
                    idle = [
                        item
                        for item in self._entries.values()
                        if item.idle and item.state == "ready"
                    ]
                    if not idle:
                        raise ProviderManagerError("provider_capacity_reached")
                    oldest = min(idle, key=lambda item: item.touched)
                    oldest.state = "stopping"
                    oldest.stop.set()
                    eviction = oldest.worker
                else:
                    owner = self._owner_factory(
                        self._settings, workspace.workspace_root
                    )
                    entry = ManagedProvider(key=key, workspace=workspace, owner=owner)
                    entry.users = 1
                    entry.slots = asyncio.Semaphore(self._max_per_provider)
                    self._entries[key] = entry
                    entry.worker = asyncio.create_task(self._run_entry(entry))
                    if self._sweeper is None and self._settings.idle_timeout_s > 0:
                        self._sweeper = asyncio.create_task(self._sweep_idle())
                    return entry
            if eviction is not None:
                try:
                    await asyncio.wait_for(
                        asyncio.shield(eviction), self._shutdown_timeout
                    )
                except asyncio.TimeoutError as exc:
                    raise ProviderManagerError("provider_eviction_unverified") from exc

    async def _sweep_idle(self) -> None:
        from .lsp_manager_eviction import sweep_idle

        await sweep_idle(self)

    async def _release(self, entry: ManagedProvider) -> None:
        abort_start = False
        async with self._lock:
            entry.users -= 1
            entry.touched = asyncio.get_running_loop().time()
            if entry.users == 0 and entry.state == "starting":
                # If the only caller abandons a cold startup, cancel it before
                # a late initialization leaves an unowned resident provider.
                entry.state = "stopping"
                entry.aborted = True
                if entry.error is None:
                    entry.error = "provider_client_aborted_start"
                entry.stop.set()
                abort_start = True
            elif (
                entry.users == 0
                and self._settings.idle_timeout_s == 0
                and entry.state == "ready"
            ):
                entry.state = "stopping"
                entry.stop.set()
        if abort_start:
            from .lsp_manager_shutdown import abort_cold_start

            await abort_cold_start(entry, self._shutdown_timeout)

    async def _poison(
        self, entry: ManagedProvider, reason: str, *, client_abort: bool = False
    ) -> None:
        async with self._lock:
            if entry.error is None:
                entry.error = reason
                if client_abort:
                    entry.aborted = True
            if entry.state != "stopping":
                entry.state = "stopping"
            entry.stop.set()

    async def definition(
        self,
        requested_file: str | Path,
        *,
        line: int,
        column: int,
        expected_symbol: str,
        allow_parent_fallback: bool = False,
    ) -> list[dict]:
        """Authorized private definition, never a public MCP tool.

        Validate source bytes and position BEFORE allocating a provider.
        Total active+waiting calls are capped; cancellation never cancels a
        shared startup but does recycle a provider after interrupted LSP IO.
        """
        self._assert_loop()
        if self._closing:
            raise ProviderManagerError("provider_manager_closing")
        # A disabled/unauthorized profile must not even inspect client source
        # paths. P2.4 still verifies the executable on actual provider launch.
        if not self._settings.enabled:
            raise ProviderManagerError("development_intelligence_disabled")
        profile = self._settings.profiles.get("pyright")
        if profile is None or not profile.enabled:
            raise ProviderManagerError("pyright_provider_disabled")
        if (
            profile.mode != "explicit_trust_only"
            or profile.source != "trusted_absolute"
        ):
            raise ProviderManagerError("pyright_provider_not_authorized")
        task = asyncio.current_task()
        if task is None:
            raise ProviderManagerError("provider_request_task_missing")
        async with self._lock:
            if self._closing:
                raise ProviderManagerError("provider_manager_closing")
            if self._outstanding >= self._max_pending:
                raise ProviderManagerError("provider_request_queue_full")
            self._outstanding += 1
            self._callers.add(task)
        entry: ManagedProvider | None = None
        try:
            # Bound admission *before* reading potentially large source data.
            workspace = AuthorizedWorkspace(
                self._allowed_roots,
                requested_file,
                allow_parent_fallback=allow_parent_fallback,
            )
            snapshot = workspace.snapshot(workspace.source_file)
            AuthorizedDocumentSession._position(
                snapshot.contents, line, column, expected_symbol
            )
            entry = await self._reserve(workspace)
            try:
                await asyncio.wait_for(
                    asyncio.shield(entry.ready.wait()), self._startup_timeout
                )
            except asyncio.TimeoutError as exc:
                from .lsp_manager_shutdown import abort_cold_start

                await self._poison(entry, "provider_start_timeout")
                # Let P2.4 stop the blocked startup; never let raw cleanup
                # exceptions escape as successful/admitted LSP responses.
                await abort_cold_start(entry, self._shutdown_timeout)
                raise ProviderManagerError("provider_start_timeout") from exc
            if self._closing or entry.state != "ready" or entry.documents is None:
                raise ProviderManagerError("provider_not_ready")
            # Provider slot first: a slow workspace must not hold global slots
            # while waiting behind another request to the same provider.
            try:
                await asyncio.wait_for(entry.slots.acquire(), self._queue_timeout)
            except asyncio.TimeoutError as exc:
                raise ProviderManagerError("provider_provider_queue_timeout") from exc
            try:
                try:
                    await asyncio.wait_for(
                        self._parallel_slots.acquire(), self._queue_timeout
                    )
                except asyncio.TimeoutError as exc:
                    raise ProviderManagerError(
                        "provider_request_queued_timeout"
                    ) from exc
                try:
                    if (
                        self._closing
                        or entry.state != "ready"
                        or entry.documents is None
                    ):
                        raise ProviderManagerError("provider_not_ready")
                    try:
                        entry.owner.observe_owned_processes()
                        # P2.5 owns the actual LSP request deadline after its
                        # document lock. An outer timer would count healthy
                        # serialization wait as server time and spuriously
                        # poison an otherwise healthy provider.
                        result = await entry.documents.definition(
                            workspace.source_file,
                            line=line,
                            column=column,
                            expected_symbol=expected_symbol,
                        )
                        entry.owner.observe_owned_processes()
                        async with self._lock:
                            if entry.state == "ready":
                                self._cooldowns.pop(entry.key, None)
                        return result
                    except asyncio.TimeoutError:
                        await self._poison(entry, "provider_request_timeout")
                        raise
                    except asyncio.CancelledError:
                        # Client abandonment requires verified recycling, but
                        # is not evidence the upstream provider malfunctioned.
                        await self._poison(
                            entry, "provider_client_cancelled", client_abort=True
                        )
                        raise
                    except Exception as exc:
                        from .lsp_workspace_access import WorkspaceAccessError

                        if (
                            not isinstance(exc, WorkspaceAccessError)
                            or entry.documents.poisoned
                        ):
                            await self._poison(entry, "provider_runtime_unverified")
                        raise
                finally:
                    self._parallel_slots.release()
            finally:
                entry.slots.release()
        finally:
            try:
                if entry is not None:
                    await self._release(entry)
            finally:
                # An owner that cannot be safely aborted may cause _release
                # to fail. That must not leak admission accounting forever.
                async with self._lock:
                    self._outstanding -= 1
                    self._callers.discard(task)

    async def aclose(self) -> ShutdownObservation:
        """Cancellation-safe close; cleanup continues if a caller is cancelled.

        Only the manager-owned close task is allowed to drain active requests
        and terminate provider owners. This operation is idempotent for all
        concurrent callers and cannot be cancelled via its waiting callers.
        """
        self._assert_loop()
        async with self._close_lock:
            if self._close_task is None:
                self._closing = True
                self._close_task = asyncio.create_task(self._finish_close())
            closing = self._close_task
        return await asyncio.shield(closing)

    async def _finish_close(self) -> ShutdownObservation:
        from .lsp_manager_shutdown import finish_manager_close

        return await finish_manager_close(self)
