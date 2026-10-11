"""OS-independent native FastMCP composition; inject long-lived domain backends.

FastMCP alone owns registration, providers, middleware, transforms and lifespan.
This module does not inspect or select the host platform, load a token from disk
or import durable jobs / Linux adapters. Normal production composition remains
in binnacle.server for backward-compatible CLI and ASGI exports.
"""

import platform
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import partial
from threading import Event, RLock
from time import time

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
from starlette.requests import Request
from starlette.responses import JSONResponse

from binnacle.config import Settings
from binnacle.features.commands.command_contracts import (
    CommandBackend,
    CommandFailure,
    ForegroundRequest,
    ForegroundResult,
    RestrictedCommandBackend,
    refuse_commands,
)
from binnacle.features.commands.commands_server import create_commands_server
from binnacle.features.files.files_server import create_files_server
from binnacle.features.files.paths import FileToolAccess
from binnacle.features.search.search_server import create_search_server
from binnacle.mcp.identity import ClientIdentity
from binnacle.mcp.logging_middleware import (
    RequestLoggingMiddleware,
    ToolLoggingMiddleware,
)
from binnacle.mcp.tool_order import PublicToolOrder
from binnacle.mcp.visibility import ClientToolVisibility, ClientToolVisibilityTransform
from binnacle.observability.log_safety import safe_request_payload
from binnacle.platform.contracts.capability_contracts import NativeCapabilityError
from binnacle.platform.contracts.darwin_contracts import (
    ForegroundExecution as NativeForegroundExecution,
)
from binnacle.platform.contracts.darwin_contracts import (
    ForegroundRequest as NativeForegroundRequest,
)
from binnacle.platform.contracts.darwin_release_scope import (
    DARWIN_RELEASE_SCOPE,
    FILE_TOOLS,
    ReleaseDecision,
)

_LINUX_INSTRUCTIONS = (
    "binnacle: a Raspberry Pi 5 development workstation. Paths live under "
    "~/Projects and /tmp. list_files (browse or glob), search_text (regex "
    "over contents), read_file, edit_file (exact-string replace), "
    "write_file (whole file), run_command (shell; long commands become "
    "jobs for job_status/stop_job). Pi hardware and health: run_command "
    "(vcgencmd, pinctrl, i2cdetect, libcamera-still)."
)
_DARWIN_INSTRUCTIONS = (
    "binnacle: a macOS workstation. Paths live under the configured roots. "
    "list_files (browse or glob), search_text (regex over contents), "
    "read_file, edit_file (exact-string replace), write_file (whole file), "
    "run_command (foreground only: no background jobs; job_status shows "
    "completed foreground runs held in memory). stop_job is unavailable on "
    "macOS. There are no board or sensor hardware tools."
)


def _server_instructions() -> str:
    # A tool map only. Workflow rules live in the ChatGPT Project's
    # instructions; tool contracts live in the tool descriptions. First 512
    # chars self-contained (OpenAI guidance).
    darwin = platform.system() == "Darwin"
    return _DARWIN_INSTRUCTIONS if darwin else _LINUX_INSTRUCTIONS


def create_application(
    *,
    settings: Settings,
    token: str,
    backend: CommandBackend,
    file_access: FileToolAccess | None = None,
    files_factory: Callable[..., FastMCP] = create_files_server,
    search_factory: Callable[..., FastMCP] = create_search_server,
    commands_factory: Callable[..., FastMCP] = create_commands_server,
) -> FastMCP:
    """Build a pure native FastMCP tree from supplied application dependencies."""
    if isinstance(backend, RestrictedCommandBackend):
        from binnacle.platform.composition import validate_native_command_states

        validate_native_command_states(
            backend.release_states,
            execution=backend.native_execution
            if isinstance(backend, _ForegroundCommandBackend)
            else None,
        )
    settings = settings.model_copy(deep=True)
    # Root authorization is fixed for this app generation. A mutable symlink
    # alias cannot silently grant new directories to an already running server.
    _ = settings.roots.canonical_allowed

    @asynccontextmanager
    async def lifespan(server):
        try:
            yield {}
        finally:
            if file_access is not None:
                file_access.close()

    native_options = {"file_access": file_access} if file_access is not None else {}
    root = FastMCP(
        "binnacle",
        lifespan=lifespan,
        on_duplicate="error",
        # A tool map only. Workflow rules live in the ChatGPT Project's
        # instructions (the single client in use); tool contracts live in the
        # tool descriptions. First 512 chars self-contained (OpenAI guidance).
        instructions=_server_instructions(),
        auth=StaticTokenVerifier(
            tokens={token: {"client_id": "binnacle-tunnel"}},
        ),
    )
    identity = ClientIdentity()
    root.add_middleware(
        RequestLoggingMiddleware(
            identity,
            include_payloads=True,
            max_payload_length=500,
            payload_serializer=partial(
                safe_request_payload, root=settings.roots.default_root
            ),
        )
    )
    root.add_middleware(
        ToolLoggingMiddleware(
            identity,
            tokenizer=settings.telemetry.tokenizer,
            path_root=settings.roots.default_root,
        )
    )
    root.add_middleware(ClientToolVisibility(settings.client_tools, identity))
    root.add_transform(PublicToolOrder())
    root.add_transform(ClientToolVisibilityTransform())
    root.mount(
        files_factory(
            **native_options,
            roots=settings.roots,
            read_settings=settings.read_file,
            list_settings=settings.list_files,
            edit_settings=settings.edit_file,
            rg_bin=settings.rg_bin,
        )
    )
    root.mount(
        search_factory(
            **native_options,
            roots=settings.roots,
            search_settings=settings.search_text,
            rg_bin=settings.rg_bin,
        )
    )
    root.mount(
        commands_factory(
            backend=backend,
            roots=settings.roots,
            run_settings=settings.run_command,
            quiet_after_s=settings.jobs.quiet_after_s,
            listing_history_limit=settings.jobs.listing_history_limit,
            listing_command_preview_chars=settings.jobs.listing_command_preview_chars,
        )
    )

    @root.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def healthz(request: Request) -> JSONResponse:
        """Process liveness only; no auth, readiness, or host-state disclosure."""
        return JSONResponse({"status": "ok"})

    return root


def compose_native_tools(
    *,
    settings: Settings,
    release_scope: Mapping[str, ReleaseDecision] = DARWIN_RELEASE_SCOPE,
):
    """Compose reviewed mechanisms; release_scope replacement is for TESTS only."""
    from uuid import uuid4

    from binnacle.features.files.paths import FileToolAccess
    from binnacle.platform.composition import (
        create_file_access,
        create_foreground_execution,
        create_search_access,
        native_file_capability,
    )

    settings = settings.model_copy(deep=True)
    release_scope = dict(release_scope)
    execution = create_foreground_execution(
        command_states={
            tool: row.capability.state.value for tool, row in release_scope.items()
        },
        foreground_limit_s=settings.run_command.wait_max_s,
        wait_max_s=settings.run_command.wait_max_s,
    )
    # Validate Commands before opening any Files resources, even for test scopes.
    capability = native_file_capability(
        release_scope=release_scope, execution=execution
    )
    files = create_file_access()
    search = (
        create_search_access(files=files, rg_bin=settings.rg_bin) if files else None
    )
    access = FileToolAccess(
        roots=settings.roots,
        files=files,
        search=search,
        generation=uuid4().hex,
        capability=capability,
        capabilities={tool: release_scope[tool].capability for tool in FILE_TOOLS},
    )
    backend = _ForegroundCommandBackend(
        execution=execution,
        keep_newest=settings.jobs.keep_newest,
        release_states={
            tool: release_scope[tool].capability.state.value
            for tool in ("run_command", "job_status", "stop_job")
        },
    )
    backend.max_output_chars = settings.jobs.max_output_chars
    return access, backend


class _ForegroundCommandBackend(RestrictedCommandBackend):
    """Application-local completed results only; no durable state or PID adoption."""

    def __init__(self, *, execution, release_states, keep_newest):
        self.native_execution = execution
        self._history: dict[str, tuple[dict, bytes]] = {}
        self._history_lock = RLock()
        self._keep_newest = keep_newest
        super().__init__(
            foreground_execution=_ForegroundDomainAdapter(execution, self._record),
            release_states=release_states,
        )

    def require_available(self) -> None:
        from binnacle.platform.composition import validate_native_command_states

        validate_native_command_states(
            self.release_states, execution=self.native_execution
        )
        super().require_available()

    def _require_history(self) -> None:
        self.require_available()
        if self.release_states.get("job_status") != "LIMITED":
            refuse_commands()

    def _record(self, request: ForegroundRequest, result: ForegroundResult) -> None:
        if self.release_states.get("job_status") != "LIMITED":
            return
        # Only a terminal result enters history, after the owner cleaned and reaped.
        state = {
            "job_id": result.execution_id,
            "state": "exited",
            "exit_code": result.exit_code,
            "signal": result.signal,
            "runtime_s": result.duration_s,
            "started_at": datetime.fromtimestamp(
                time() - result.duration_s, timezone.utc
            ).isoformat(),
            "workdir": str(request.workdir),
            "command": request.command,
            "last_output_age_s": None,
            "log_bytes": len(result.output),
            "log_path": "",
        }
        with self._history_lock:
            self._history[result.execution_id] = (state, result.output)
            while len(self._history) > self._keep_newest:
                del self._history[next(iter(self._history))]

    def job_state(self, job_id: str) -> dict | None:
        self._require_history()
        with self._history_lock:
            entry = self._history.get(job_id)
            return dict(entry[0]) if entry else None

    def list_jobs(self) -> list[dict]:
        self._require_history()
        with self._history_lock:
            return [dict(state) for state, _ in reversed(self._history.values())]

    def await_exit(self, job_id: str, timeout: float) -> dict | None:
        return self.job_state(job_id)

    def read_log(self, job_id: str) -> bytes:
        self._require_history()
        with self._history_lock:
            entry = self._history.get(job_id)
            if entry is None:
                raise CommandFailure("foreground_history_unavailable")
            return entry[1]

    def read_log_range(
        self, job_id: str, start: int, max_bytes: int
    ) -> tuple[bytes, int]:
        output = self.read_log(job_id)
        return output[start : start + max_bytes], len(output)


class _ForegroundDomainAdapter:
    """Map native values/errors to the portable Commands execution protocol."""

    def __init__(
        self,
        execution: NativeForegroundExecution,
        on_result: Callable[[ForegroundRequest, ForegroundResult], None],
    ) -> None:
        self.execution = execution
        self.on_result = on_result

    def run_foreground(
        self, request: ForegroundRequest, *, cancel: Event
    ) -> ForegroundResult:
        native = NativeForegroundRequest(
            request.command,
            request.workdir,
            request.stdin,
            request.wait_seconds,
            request.background,
            request.foreground_limit_s,
            request.max_output_bytes,
        )
        try:
            result = self.execution.run_foreground(native, cancel=cancel)
        except NativeCapabilityError as exc:
            marker = (
                "; descendants_unverified=true"
                if "descendants_unverified=true" in str(exc)
                else ""
            )
            raise CommandFailure(
                f"{exc.code}: {exc.capability.state.value}{marker}"
            ) from exc
        mapped = ForegroundResult(
            result.execution_id,
            result.owner_generation,
            result.exit_code,
            result.signal,
            result.output,
            result.output_bytes,
            result.truncated,
            result.duration_s,
            result.descendants_unverified,
        )
        self.on_result(request, mapped)
        return mapped
