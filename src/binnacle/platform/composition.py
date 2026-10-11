"""Single host-selection boundary for native OS mechanisms.

Darwin adapters remain limited mechanisms, with public runtime review-gated.
Domain services consume small platform contracts; they do not select the host or import its implementation.
This module is normal Python composition, not a FastMCP Provider or registry.
"""

import platform
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Literal

from binnacle.platform.contracts.capability_contracts import CapabilityState
from binnacle.platform.contracts.darwin_contracts import (
    ForegroundExecution,
    ForegroundRequest,
    ForegroundResult,
    OwnedWitness,
    OwnerGeneration,
)
from binnacle.platform.contracts.darwin_release_scope import (
    DARWIN_RELEASE_SCOPE,
    FILE_TOOLS,
)
from binnacle.platform.contracts.file_access_contracts import FileAccess, SearchAccess
from binnacle.platform.contracts.native_service_contracts import (
    AuthenticatedChannel,
    NativeRequestHandler,
    ServiceLease,
)
from binnacle.platform.contracts.process_contracts import ProcessBackend
from binnacle.platform.contracts.resource_contracts import ResourceAccounting
from binnacle.platform.contracts.runtime_path_contracts import RuntimePaths
from binnacle.platform.contracts.service_lifecycle_contracts import (
    ManagedServiceController,
    ManagedServiceInspector,
)
from binnacle.platform.contracts.service_log_contracts import ServiceLogSource

if TYPE_CHECKING:
    from binnacle.platform.darwin.process_backend import DarwinProcessBackend
    from binnacle.platform.darwin.resource_accounting import DarwinResourceAccounting


class UnsupportedHostOS(RuntimeError):
    """The host has no installed Binnacle platform implementation."""


def host_os_family(system: str | None = None) -> Literal["linux", "darwin"]:
    """Resolve the OS once at the boundary, never silently fall back to Linux."""
    name = platform.system() if system is None else system
    if name not in ("Linux", "Darwin"):
        raise UnsupportedHostOS(f"Binnacle has no {name!r} platform adapter")
    return "linux" if name == "Linux" else "darwin"


def create_process_backend(*, witness: OwnedWitness | None = None) -> ProcessBackend:
    if host_os_family() == "darwin":
        from binnacle.platform.darwin.process_backend import DarwinProcessBackend

        return DarwinProcessBackend(witness=witness)
    from binnacle.platform.linux.job_process import LinuxProcessBackend

    return LinuxProcessBackend()


def create_resource_accounting() -> ResourceAccounting:
    if host_os_family() == "darwin":
        from binnacle.platform.darwin.resource_accounting import (
            DarwinResourceAccounting,
        )

        return DarwinResourceAccounting()
    from binnacle.platform.linux.job_cgroup import CgroupResourceAccounting

    return CgroupResourceAccounting()


def create_runtime_paths() -> RuntimePaths:
    if host_os_family() == "darwin":
        from binnacle.platform.darwin.generation_runtime import resolve_runtime_paths

        return resolve_runtime_paths()
    from binnacle.platform.linux.runtime_paths_linux import resolve_runtime_paths

    return resolve_runtime_paths()


def create_service_log_source(
    *,
    command_timeout_s: float | None = None,
    root: Path | None = None,
    generation: str | None = None,
) -> ServiceLogSource:
    if host_os_family() == "darwin":
        if root is None or generation is None:
            raise UnsupportedHostOS(
                "Darwin service logs require an explicit root and generation"
            )
        from binnacle.platform.darwin.log_source import PrivateServiceLogSource

        return PrivateServiceLogSource(root=root, generation=generation)
    from binnacle.platform.linux.service_journal import JournalServiceLogSource

    return JournalServiceLogSource(command_timeout_s=command_timeout_s)


def create_service_inspector(
    *, lease: ServiceLease | None = None
) -> ManagedServiceInspector:
    if host_os_family() == "darwin":
        if lease is None:
            raise UnsupportedHostOS(
                "Darwin service requires an explicit generation lease"
            )
        from binnacle.platform.darwin.service_launchd import LaunchdUserServices

        return LaunchdUserServices(lease)
    from binnacle.platform.linux.service_systemd import SystemdUserServices

    return SystemdUserServices()


def create_service_controller(
    *, lease: ServiceLease | None = None
) -> ManagedServiceController:
    if host_os_family() == "darwin":
        if lease is None:
            raise UnsupportedHostOS(
                "Darwin service requires an explicit generation lease"
            )
        from binnacle.platform.darwin.service_launchd import LaunchdUserServices

        return LaunchdUserServices(lease)
    from binnacle.platform.linux.service_systemd import SystemdUserServices

    return SystemdUserServices()


def create_linux_provisioner(*, unit_dir=None, backup_dir=None, run=None):
    """Linux-only setup compatibility, not a generic cross-OS provisioner."""
    if host_os_family() != "linux":
        raise UnsupportedHostOS("Linux-only service operation")
    from binnacle.platform.linux.service_provisioning_linux import (
        DEFAULT_BACKUP_DIR,
        UNIT_DIR,
        LinuxServiceProvisioner,
    )

    return LinuxServiceProvisioner(
        unit_dir=UNIT_DIR if unit_dir is None else unit_dir,
        backup_dir=DEFAULT_BACKUP_DIR if backup_dir is None else backup_dir,
        run=run,
    )


def notify_job_manager_ready(on_error):
    """Linux unit readiness hook; durable RPC remains Core-owned."""
    if host_os_family() != "linux":
        raise UnsupportedHostOS("Linux-only service operation")
    from binnacle.platform.linux.notify_systemd import notify_ready

    notify_ready(on_error)


def create_file_access() -> FileAccess | None:
    """Construct the native mechanism; this does not enable public tools."""
    if host_os_family() == "linux":
        return None
    from binnacle.platform.darwin.file_access import DarwinFileAccess

    return DarwinFileAccess()


def create_search_access(*, files: FileAccess, rg_bin: str) -> SearchAccess:
    if host_os_family() != "darwin":
        raise UnsupportedHostOS("Opened Files/Search composition requires Darwin")
    from binnacle.platform.darwin.search_access import DarwinSearchAccess

    return DarwinSearchAccess(files, rg_bin=rg_bin)


def create_service_log_writer(
    *, root: Path, generation: str, service: str, redact_values=()
):
    if host_os_family() != "darwin":
        raise UnsupportedHostOS("Private service writer requires Darwin")
    from binnacle.platform.darwin.log_source import PrivateServiceLogWriter

    return PrivateServiceLogWriter(
        root=root, generation=generation, service=service, redact_values=redact_values
    )


def create_service_lease(
    *, root: Path, label: str, generation: str | None = None
) -> ServiceLease:
    """Create fresh per-start authority; explicit generations support test peers."""
    if host_os_family() != "darwin":
        raise UnsupportedHostOS("Native service lease requires Darwin")
    from binnacle.platform.darwin.generation_runtime import open_service_lease

    if generation is None:
        from secrets import token_hex

        generation = token_hex(16)
    return open_service_lease(root=root, label=label, generation=generation)


def connect_native_channel(*, socket_path: Path, lease: ServiceLease, timeout_s: float):
    if host_os_family() != "darwin":
        raise UnsupportedHostOS("Native authenticated channel requires Darwin")
    import time

    from binnacle.platform.contracts.capability_contracts import NativeCapabilityError
    from binnacle.platform.darwin.ipc_transport import connect_authenticated

    # A3 caps channels at 16 with backlog 8. Retry only the authenticated
    # connection/readiness handshake; never replay a dispatched RPC mutation.
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            return connect_authenticated(socket_path, lease=lease, timeout_s=timeout_s)
        except NativeCapabilityError as exc:
            remaining = deadline - time.monotonic()
            if (
                exc.code not in ("ipc_connect_refused", "ipc_connect_timeout")
                or remaining <= 0
            ):
                raise
            time.sleep(min(0.02, remaining))
            timeout_s = max(0.000001, deadline - time.monotonic())


def serve_native_channel(
    *,
    socket_path: Path,
    lease: ServiceLease,
    handler: NativeRequestHandler,
    stop: Event,
):
    """Forward concurrent bounded handlers; callers own locks and idempotency.

    Capacity is 16 channels with listen backlog 8; keep long-lived witness
    channels well below capacity. Saturation can temporarily deny readiness.
    No production Darwin manager or mutating RPC handler is enabled here.
    """
    if host_os_family() != "darwin":
        raise UnsupportedHostOS("Native authenticated channel requires Darwin")
    from binnacle.platform.darwin.ipc_transport import serve_authenticated

    serve_authenticated(socket_path, lease=lease, handler=handler, stop=stop)


def validate_native_command_states(
    states: Mapping[str, str], *, execution: ForegroundExecution | None = None
) -> None:
    """Reject contradictory scopes, including explicit candidate test mappings."""
    if states.get("stop_job", "UNAVAILABLE") != "UNAVAILABLE":
        raise RuntimeError("Darwin stop_job must remain UNAVAILABLE")
    if host_os_family() != "darwin":
        return
    from binnacle.platform.darwin.process_backend import DarwinProcessBackend

    if isinstance(execution, _ObservedForegroundExecution):
        execution.process.validate_release_states(states)
    else:
        DarwinProcessBackend().validate_release_states(states)


def native_file_capability(*, release_scope=DARWIN_RELEASE_SCOPE, execution=None):
    """Read the committed scope; explicit alternatives are test harness inputs."""
    validate_native_command_states(
        {tool: row.capability.state.value for tool, row in release_scope.items()},
        execution=execution,
    )
    if host_os_family() == "linux":
        return None
    capabilities = [release_scope[tool].capability for tool in FILE_TOOLS]
    return max(capabilities, key=lambda cap: cap.state == CapabilityState.LIMITED)


def create_native_provisioner(*, root: Path, lease: ServiceLease):
    """Map A6 inert plans; native lifecycle acceptance remains a separate gate.

    A6 omits raw launchd output paths. The service entrypoint writes records
    through A5 with the generation embedded here, never to an unredacted file.
    """
    if host_os_family() != "darwin":
        raise UnsupportedHostOS("Native provisioning requires Darwin")
    import os

    from binnacle.deployment.darwin.provisioner import DarwinProvisioner
    from binnacle.platform.darwin.generation_runtime import validate_lease

    fd = validate_lease(root, lease)
    os.close(fd)
    return _NativeProvisionerMapping(
        DarwinProvisioner(root, uid=lease.uid, lifecycle=None)
    )


class _NativeProvisionerMapping:
    def __init__(self, provisioner):
        self._provisioner = provisioner

    def plan(self, lease: ServiceLease, *, argv, environment, workdir):
        from binnacle.deployment.darwin import provisioner as local
        from binnacle.platform.contracts.native_service_contracts import ServicePlan

        mapped = local.ServiceLease(
            lease.uid,
            lease.label,
            lease.generation,
            lease.root_device,
            lease.root_inode,
        )
        try:
            plan = self._provisioner.plan(
                mapped,
                argv=argv,
                environment={
                    **environment,
                    "BINNACLE_SERVICE_GENERATION": lease.generation,
                },
                workdir=workdir,
            )
        except local.ProvisionError as exc:
            self._raise_mapped(exc)
        return ServicePlan(
            lease, plan.plist_bytes, plan.plist_path, plan.expected_previous_sha256
        )

    @staticmethod
    def _raise_mapped(exc):
        from binnacle.deployment.darwin import provisioner as local
        from binnacle.platform.contracts import capability_contracts as native

        error_type: type[native.NativeCapabilityError] = native.UnsafePath
        if isinstance(exc, local.GenerationMismatch):
            error_type = native.GenerationMismatch
        elif isinstance(exc, local.CapabilityUnavailable):
            error_type = native.CapabilityUnavailable
        cap = native.Capability(
            native.CapabilityState(exc.capability.state),
            exc.capability.reason_code,
            exc.capability.scope,
        )
        raise error_type(exc.code, cap) from exc

    def apply(self, plan):
        self._refuse_handoff()

    def rollback(self, plan):
        self._refuse_handoff()

    @staticmethod
    def _refuse_handoff():
        from binnacle.platform.contracts.capability_contracts import (
            Capability,
            CapabilityState,
            CapabilityUnavailable,
        )

        code = "darwin_service_handoff_incomplete"
        raise CapabilityUnavailable(
            code,
            Capability(
                CapabilityState.UNAVAILABLE,
                code,
                "A3/A5/A6 integration; FULL_PARITY_NO_GO",
            ),
        )


def create_owned_witness(
    *, channel: AuthenticatedChannel, generation: OwnerGeneration
) -> OwnedWitness:
    """Read-only A2 observation on an authenticated A3 channel; never enrollment."""
    if host_os_family() != "darwin":
        raise UnsupportedHostOS("Native owned witness requires Darwin")
    from binnacle.platform.darwin.witness_protocol import DarwinWitness

    return DarwinWitness(channel, generation)


class _ObservedForegroundExecution:
    """Bind A2's sole-reaper observation to A5 without observing PIDs ourselves."""

    def __init__(
        self, process: "DarwinProcessBackend", accounting: "DarwinResourceAccounting"
    ) -> None:
        self.process, self.accounting = process, accounting

    def run_foreground(
        self, request: ForegroundRequest, *, cancel: Event
    ) -> ForegroundResult:
        from dataclasses import replace
        from uuid import uuid4

        observation_id = uuid4().hex
        result = self.process.run_foreground(
            request,
            cancel=cancel,
            on_direct_child_exit=lambda usage: self.accounting.record_direct_child_exit(
                observation_id, usage
            ),
        )
        return replace(result, execution_id=observation_id)


def create_foreground_execution(
    *, command_states=None, foreground_limit_s=50, wait_max_s=50
) -> ForegroundExecution:
    """Inject A2 only for the composed LIMITED row; bind its sole reaper to A5."""
    if host_os_family() != "darwin":
        raise UnsupportedHostOS("Native foreground execution requires Darwin")
    from binnacle.platform.darwin.process_backend import (
        DarwinProcessBackend,
        _ForegroundRunner,
    )
    from binnacle.platform.darwin.resource_accounting import DarwinResourceAccounting

    states = command_states or {}
    runner = (
        _ForegroundRunner(foreground_limit_s, wait_max_s)
        if states.get("run_command") == "LIMITED"
        else None
    )
    execution = _ObservedForegroundExecution(
        DarwinProcessBackend(foreground_runner=runner), DarwinResourceAccounting()
    )
    validate_native_command_states(states, execution=execution)
    return execution


@contextmanager
def native_service_output():
    """Route A6 service stdout/stderr and root logging through A5's sole writer."""
    import io
    import logging
    import os
    from contextlib import redirect_stderr, redirect_stdout
    from threading import RLock

    root = os.environ.get("BINNACLE_RUNTIME_DIR")
    role = os.environ.get("BINNACLE_SERVICE_ROLE")
    if host_os_family() != "darwin" or root is None or role is None:
        yield
        return
    generation = os.environ.get("BINNACLE_SERVICE_GENERATION")
    if role not in ("frontend", "probe", "manager") or not generation:
        raise UnsupportedHostOS("Native service log generation/role missing")
    writer = create_service_log_writer(
        root=Path(root), generation=generation, service=role
    )
    lock = RLock()

    class Output(io.TextIOBase):
        def __init__(self):
            self.pending = ""
            self.overflow = False

        def write(self, text):
            with lock:
                for piece in text.splitlines(keepends=True):
                    self.pending += piece
                    if len(self.pending) > 65536:
                        self.pending, self.overflow = "", True
                    if piece.endswith("\n"):
                        writer.write(
                            "[oversized record omitted]"
                            if self.overflow
                            else self.pending
                        )
                        self.pending, self.overflow = "", False
            return len(text)

        def flush(self):
            # Do not persist fragments: a credential may span separate writes.
            with lock:
                writer.sync()

    writer.start()
    output = Output()
    logger = logging.getLogger()
    old_handlers = logger.handlers[:]
    handler = logging.StreamHandler(output)
    logger.handlers = [handler]
    try:
        with redirect_stdout(output), redirect_stderr(output):
            yield
    finally:
        logger.handlers = old_handlers
        with lock:
            if output.pending or output.overflow:
                writer.write("[unterminated record omitted]")
            writer.close()
