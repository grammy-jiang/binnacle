"""P2.4 private process lifetime for the *upstream* multilspy PyrightServer.

No adapter, LSP protocol, editor state or MCP tool is implemented here.
Importing this module is inert; all provider imports and launches are lazy.
A caller must supply an already-authorized disposable workspace (P2.5 owns
workspace authorization). This private component is not production-mounted.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from binnacle.config_development_intelligence import DevelopmentIntelligenceSettings
from binnacle.features.development_intelligence.lsp_process_tree import (
    NativeProviderTree,
    ProcessCleanup,
)

# P3.3 credential-hygiene allowlist for native multilspy Pyright subprocesses.
# This does NOT isolate filesystem, network or children. HOME may be inferred
# from passwd. PATH is supplied separately from the admitted Node installation.
_PYRIGHT_PARENT_ENV_KEYS = ("LANG", "LC_ALL", "LC_CTYPE", "TZ")


class ProviderLifecycleError(RuntimeError):
    """A provider lifetime was denied or could not be safely completed."""


@dataclass(frozen=True)
class ProviderExitEvidence:
    """Observed local process cleanup; NOT an OS sandbox/descendant proof."""

    pid: int | None
    parent_exited: bool
    pending_requests: int
    reader_tasks: int
    cleanup_unverified: bool
    descendants_audited: bool = False
    observed_descendants: tuple[int, ...] = ()
    lingering_descendants: tuple[int, ...] = ()
    escaped_descendants: tuple[int, ...] = ()
    containment_verified: bool = False


class PrivatePyrightProcessOwner:
    """One explicitly trusted Pyright lifespan, never an agent-facing API.

    This is the narrow P2.4 process owner. Per-workspace registry, concurrent
    agent request scheduling and resident caching remain the P2.6 manager's
    responsibility; successful local stop cannot certify confinement.
    """

    def __init__(
        self,
        settings: DevelopmentIntelligenceSettings,
        workspace_root: Path,
        *,
        operator_allowed_roots: tuple[Path, ...],
        cleanup_timeout_s: float = 25.0,
        sandbox_mode: Literal["none", "linux_bwrap_experimental"] = "none",
    ) -> None:
        if not settings.enabled:
            raise ProviderLifecycleError("development_intelligence_disabled")
        profile = settings.profiles.get("pyright")
        if profile is None or not profile.enabled:
            raise ProviderLifecycleError("pyright_provider_disabled")
        if profile.mode != "explicit_trust_only":
            raise ProviderLifecycleError("pyright_requires_explicit_trust")
        if profile.source != "trusted_absolute" or not profile.executable:
            raise ProviderLifecycleError("pyright_requires_trusted_absolute_executable")
        if profile.argv or profile.env:
            raise ProviderLifecycleError("unaudited_pyright_process_options")
        if profile.languages and "python" not in profile.languages:
            raise ProviderLifecycleError("pyright_profile_language_not_supported")
        binary = Path(profile.executable)
        if not binary.is_absolute() or not binary.is_file():
            raise ProviderLifecycleError("pyright_executable_unavailable")
        root = Path(workspace_root).resolve(strict=True)
        if not root.is_dir():
            raise ProviderLifecycleError("workspace_not_directory")
        # The explicit host-provided executable must not be resident inside
        # the untrusted workspace, including a symlink into it. This is a
        # conservative selection guard, not TOCTOU-proof OS sandboxing.
        resolved_binary = binary.resolve(strict=True)
        if binary.is_relative_to(root) or resolved_binary.is_relative_to(root):
            raise ProviderLifecycleError("pyright_executable_inside_workspace")
        # The requested file belongs to one workspace, but Binnacle grants
        # the agent read/write authority to *all* operator-approved roots.
        # An executable from any such root is mutable by an authenticated MCP
        # user even when it is outside the current Python project.
        if not isinstance(operator_allowed_roots, tuple) or not operator_allowed_roots:
            raise ProviderLifecycleError("operator_roots_required")
        approved = []
        for configured_root in operator_allowed_roots:
            try:
                granted = Path(configured_root).expanduser().resolve(strict=True)
            except (OSError, ValueError) as exc:
                raise ProviderLifecycleError("operator_root_unavailable") from exc
            if not granted.is_dir():
                raise ProviderLifecycleError("operator_root_not_directory")
            approved.append(granted)
            if binary.is_relative_to(granted) or resolved_binary.is_relative_to(
                granted
            ):
                raise ProviderLifecycleError("pyright_executable_inside_operator_root")
        if not any(root.is_relative_to(grant) for grant in approved):
            raise ProviderLifecycleError("workspace_outside_operator_roots")
        if (
            isinstance(cleanup_timeout_s, bool)
            or not isinstance(cleanup_timeout_s, (float, int))
            or not 0 < cleanup_timeout_s <= 120
        ):
            raise ValueError("invalid_provider_cleanup_deadline")
        self._root = root
        self._binary = resolved_binary
        self._selected_binary = binary
        self._operator_roots = tuple(approved)
        self._cleanup_timeout_s = float(cleanup_timeout_s)
        if sandbox_mode not in ("none", "linux_bwrap_experimental"):
            raise ProviderLifecycleError("unreviewed_private_sandbox_mode")
        # This is a private explicit constructor argument, NOT a config option
        # or agent-facing capability. No READ eligibility derives from it.
        self._sandbox_mode = sandbox_mode
        self._active = False
        self._entered = False
        self._session_task: asyncio.Task | None = None
        self._closed = False
        self._poisoned = False
        self._server: Any | None = None
        self._tree: NativeProviderTree | None = None
        self.last_exit: ProviderExitEvidence | None = None

    @property
    def active(self) -> bool:
        return self._active

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def process_running(self) -> bool:
        """Liveness of the exact provider already owned by this instance."""
        server = self._server
        process = server.server.process if server is not None else None
        return self._active and process is not None and process.returncode is None

    def _make_upstream_server(self) -> Any:
        """Import only the optional pinned fork, and only upon actual launch."""
        node = self._admit_node_launch()
        from multilspy import LanguageServer  # type: ignore[import-untyped]
        from multilspy.multilspy_config import (  # type: ignore[import-untyped]
            Language,
            MultilspyConfig,
        )
        from multilspy.multilspy_logger import (  # type: ignore[import-untyped]
            MultilspyLogger,
        )

        server = LanguageServer.create(
            MultilspyConfig(
                code_language=Language.PYTHON,
                python_server="pyright",
                server_binary=str(self._binary),
                trace_lsp_communication=False,
                inherited_environment_keys=_PYRIGHT_PARENT_ENV_KEYS,
            ),
            MultilspyLogger(),
            str(self._root),
        )
        launch = server.server.process_launch_info
        if launch.cmd != [str(self._binary), "--stdio"] or launch.env:
            raise ProviderLifecycleError("pyright_launch_contract_changed")
        # Reuse upstream PR #168 for protocol/lifecycle behavior. The Linux
        # experiment keeps the same LSP absolute workspace URIs and process
        # ownership but wraps the actual Node in OS namespaces. No runtime
        # config, READ, or public tool is enabled by this private branch.
        if self._sandbox_mode == "linux_bwrap_experimental":
            from binnacle.features.development_intelligence.lsp_linux_bwrap import (
                SandboxLaunchRefused,
                build_private_bwrap_launch,
            )

            try:
                bwrap = self._admit_launch_file(Path("/usr/bin/bwrap"))
                launch.cmd = build_private_bwrap_launch(
                    node=node, launcher=self._binary, workspace=self._root, bwrap=bwrap
                )
            except (OSError, ValueError, SandboxLaunchRefused) as exc:
                raise ProviderLifecycleError(
                    "experimental_linux_sandbox_launch_denied"
                ) from exc
            launch.env = {}
        else:
            # Native trust-only baseline. Bypass env's shebang lookup and never
            # mutate the parent environment (concurrent owners).
            launch.cmd = [str(node), str(self._binary), "--stdio"]
            launch.env = {"PATH": str(node.parent)}
        return server

    def _admit_launch_file(self, selected: Path) -> Path:
        """Reject writable-root traversal, including intermediate symlinks.

        This is a selection check, not an atomic open/exec or hardlink/mount
        identity proof. Operator-owned installations must remain trusted.
        """
        pending = list(selected.parts[1:])
        current = Path(selected.anchor).resolve(strict=True)
        links = 0
        while pending:
            part = pending.pop(0)
            current = current.parent if part == ".." else current / part
            if any(current.is_relative_to(root) for root in self._operator_roots):
                raise ProviderLifecycleError("pyright_launch_inside_operator_root")
            if current.is_symlink():
                links += 1
                if links > 40:
                    raise ProviderLifecycleError("pyright_launch_symlink_cycle")
                target = current.readlink()
                if not target.is_absolute():
                    target = current.parent / target
                pending = list(target.parts[1:]) + pending
                current = Path(target.anchor).resolve(strict=True)
        if not current.is_file() or not os.access(current, os.X_OK):
            raise ProviderLifecycleError("pyright_launch_file_unavailable")
        return current

    def _admit_node_launch(self) -> Path:
        """Only the native npm launcher and its selected sibling Node qualify.

        No PATH search or fallback. A trusted launcher alias and sibling node
        alias may point to separately installed, trusted package/runtime trees.
        Recheck each launch; arbitrary wrappers/interpreter chains fail closed.
        """
        try:
            binary = self._admit_launch_file(self._selected_binary)
            if binary != self._binary:
                raise ProviderLifecycleError("pyright_launcher_retargeted")
            with binary.open("rb") as stream:
                if stream.readline(128) != b"#!/usr/bin/env node\n":
                    raise ProviderLifecycleError("pyright_launcher_not_audited")
            node = self._admit_launch_file(self._selected_binary.parent / "node")
            with node.open("rb") as stream:
                magic = stream.read(4)
            # Native ELF / Mach-O (including universal) only, never another
            # env script. This rejects chains; it does not certify Node bytes.
            if magic not in (
                b"\x7fELF",
                b"\xcf\xfa\xed\xfe",
                b"\xfe\xed\xfa\xcf",
                b"\xca\xfe\xba\xbe",
                b"\xca\xfe\xba\xbf",
            ):
                raise ProviderLifecycleError("pyright_node_not_native")
            return node
        except (OSError, ValueError) as exc:
            raise ProviderLifecycleError("pyright_launch_admission_failed") from exc

    def observe_owned_processes(self) -> None:
        """Sample only our verified process group and descendants.

        P2.6 can call this on admitted requests. Escaped descendants that
        disappear between samples cannot be ruled out without an OS sandbox.
        """
        if not self._active or self._tree is None:
            raise ProviderLifecycleError("provider_process_not_active")
        self._tree.observe()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[Any]:
        """Enter/exit one upstream Pyright lifespan and record cleanup proof."""
        if self._closed or self._poisoned:
            raise ProviderLifecycleError("provider_owner_closed_or_unverified")
        if self._active:
            raise ProviderLifecycleError("provider_owner_busy")
        self._active = True
        self._session_task = asyncio.current_task()
        server = None
        process = None
        cleanup_error = None
        tree = NativeProviderTree()
        result: ProcessCleanup | None = None
        try:
            server = self._make_upstream_server()
            self._server = server
            async with server.start_server():
                process = server.server.process
                if process is None:
                    raise ProviderLifecycleError("provider_process_not_started")
                # The provider must be an independently spawned POSIX session;
                # never capture the parent Binnacle MCP process group.
                tree.capture(process.pid)
                self._tree = tree
                tree.observe()
                if self._closed:
                    raise ProviderLifecycleError("provider_closed_during_startup")
                try:
                    self._entered = True
                    yield server
                finally:
                    self._entered = False
                    # Observe descendants before multilspy stops the leader.
                    # The policy is still explicit-trust-only without sandbox.
                    tree.observe()
        finally:
            if server is not None and server.server.process is not None:
                try:
                    # Backstop for failed/cancelled adapter exits. In normal
                    # operation multilspy has already closed its own process.
                    await asyncio.wait_for(
                        server.server.stop(), timeout=self._cleanup_timeout_s
                    )
                except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001
                    cleanup_error = exc
            try:
                # Native backstop owns only (PID, birth-time, process-group)
                # identities it actually observed. Never signal a PID from
                # source files, logs, client input or a previous generation.
                result = await asyncio.wait_for(
                    tree.cleanup(), timeout=self._cleanup_timeout_s
                )
            except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001
                cleanup_error = exc
            if server is not None:
                handler = server.server
                observed = tuple(
                    sorted(
                        pid
                        for pid in tree.members
                        if tree.root and pid != tree.root.pid
                    )
                )
                lingering = (
                    tuple(
                        pid
                        for pid in result.remaining
                        if tree.root and pid != tree.root.pid
                    )
                    if result is not None
                    else observed
                )
                evidence = ProviderExitEvidence(
                    pid=getattr(process, "pid", None),
                    parent_exited=process is not None
                    and process.returncode is not None,
                    pending_requests=len(handler._response_handlers),
                    reader_tasks=sum(
                        not task.done() for task in handler.tasks.values()
                    ),
                    cleanup_unverified=bool(
                        self._poisoned
                        or cleanup_error
                        or result is None
                        or result.status != "observed_clean"
                        or (process is not None and process.returncode is None)
                        or handler.process is not None
                        or handler._response_handlers
                        or any(not task.done() for task in handler.tasks.values())
                    ),
                    descendants_audited=result is not None
                    and result.root_pid is not None,
                    observed_descendants=observed,
                    lingering_descendants=lingering,
                    escaped_descendants=tuple(sorted(tree.escaped)),
                )
                self.last_exit = evidence
                if evidence.cleanup_unverified:
                    self._poisoned = True
            self._tree = None
            self._server = None
            self._active = False
            self._entered = False
            self._session_task = None
            if cleanup_error is not None:
                raise ProviderLifecycleError(
                    "provider_cleanup_unverified"
                ) from cleanup_error
            if self._poisoned:
                raise ProviderLifecycleError("provider_cleanup_unverified")

    async def aclose(self) -> None:
        """Stop admitting sessions, including one still in native initialize."""
        self._closed = True
        starting = self._session_task
        if (
            self._active
            and not self._entered
            and starting is not None
            and starting is not asyncio.current_task()
        ):
            # Abort before an awaited upstream initialize can start a process
            # *after* aclose has returned. Await the recorded session cleanup.
            starting.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.shield(starting), timeout=self._cleanup_timeout_s
                )
            except (asyncio.CancelledError, ProviderLifecycleError):
                pass
            except asyncio.TimeoutError as exc:
                self._poisoned = True
                raise ProviderLifecycleError("provider_cleanup_unverified") from exc
            return
        server = self._server
        if server is not None and server.server.process is not None:
            try:
                await asyncio.wait_for(
                    server.server.stop(), timeout=self._cleanup_timeout_s
                )
            except asyncio.CancelledError:
                self._poisoned = True
                raise
            except Exception as exc:
                self._poisoned = True
                raise ProviderLifecycleError("provider_cleanup_unverified") from exc
