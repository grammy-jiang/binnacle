"""Optional native lifespan owner of the private MCP maintenance A3 sidecar.

The installed default remains OFF. Explicit configuration must supply an
already existing 0700 private root. Startup waits for authenticated A3
generation readiness before serving client requests; shutdown joins the
sidecar without touching launchd, Jobs or Watchdog. This is *not* an
out-of-process controller or authority to stop MCP.
"""

from __future__ import annotations

import logging
import os
import stat
import threading
import time
from pathlib import Path

from binnacle.platform.contracts.maintenance_contracts import MCPAdmissionGate
from binnacle.platform.contracts.native_service_contracts import ServiceLease
from binnacle.platform.darwin.mcp_maintenance_admission_rpc import (
    _DIR,
    _LABEL,
    _SOCKET,
    read_mcp_admission_a3,
    serve_mcp_admission_a3,
)

_LOG = logging.getLogger(__name__)


class MCPMaintenanceRuntimeRefused(RuntimeError):
    """Start-up or teardown of the control sidecar was not safely verified."""


class MCPMaintenanceAdmissionRuntime:
    """One A3 sidecar per MCP server process generation, never a global service."""

    def __init__(self, root: Path, gate: MCPAdmissionGate) -> None:
        self.root = root
        self.gate = gate
        self._state = threading.Lock()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._failure: Exception | None = None
        self.lease: ServiceLease | None = None

    def _private(self) -> None:
        if (
            os.getuid() == 0
            or os.geteuid() != os.getuid()
            or not self.root.is_absolute()
            or self.root.name != _DIR
            or self.root.resolve() != self.root
        ):
            raise MCPMaintenanceRuntimeRefused(
                "configured MCP maintenance runtime is not trusted"
            )
        try:
            info = self.root.lstat()
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700
            ):
                raise MCPMaintenanceRuntimeRefused(
                    "configured MCP control directory not private"
                )
        except OSError as exc:
            raise MCPMaintenanceRuntimeRefused(
                "configured MCP maintenance root not available"
            ) from exc

    def start(self, *, timeout_s: float = 3.0) -> None:
        """Start a separately authenticated sidecar or fail the MCP lifespan."""
        if not 0 < timeout_s <= 10:
            raise MCPMaintenanceRuntimeRefused("invalid sidecar readiness deadline")
        with self._state:
            if self._worker is not None:
                raise MCPMaintenanceRuntimeRefused(
                    "MCP maintenance sidecar already started"
                )
            self._private()
            from binnacle.platform.darwin.generation_runtime import open_service_lease

            lease = open_service_lease(
                root=self.root, label=_LABEL, generation=self.gate.generation
            )
            self.lease = lease
            self._stop.clear()
            self._failure = None

            def serve() -> None:
                try:
                    serve_mcp_admission_a3(
                        self.root / _SOCKET,
                        lease=lease,
                        gate=self.gate,
                        stop=self._stop,
                    )
                except Exception as exc:  # noqa: BLE001 - thread lifetime boundary
                    # A3 thread errors are not hidden from the lifespan.
                    self._failure = exc

            worker = threading.Thread(
                target=serve,
                name="binnacle-mcp-maintenance-a3",
                daemon=True,
            )
            self._worker = worker
            worker.start()
        try:
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                if self._failure is not None or not worker.is_alive():
                    break
                try:
                    snapshot = read_mcp_admission_a3(
                        self.root / _SOCKET,
                        lease=lease,
                        generation=self.gate.generation,
                        timeout_s=min(0.25, max(0.001, deadline - time.monotonic())),
                    )
                    if snapshot.pause_nonce is None and snapshot.in_flight == 0:
                        return
                except Exception:  # noqa: BLE001 - bounded readiness retry
                    _LOG.debug("mcp_maintenance_a3_readiness_retry")
                time.sleep(0.04)
            raise MCPMaintenanceRuntimeRefused(
                "MCP maintenance A3 sidecar not authenticated and ready"
            )
        except BaseException:
            self.stop()
            raise

    def stop(self) -> None:
        """Signal sidecar shutdown and require a bounded successful join."""
        with self._state:
            worker = self._worker
            self._stop.set()
            if worker is None:
                return
        worker.join(timeout=4)
        if worker.is_alive():
            raise MCPMaintenanceRuntimeRefused("MCP maintenance sidecar failed to stop")
        with self._state:
            self._worker = None
            self.lease = None
            failed = self._failure
            self._failure = None
        if failed is not None:
            raise MCPMaintenanceRuntimeRefused(
                "MCP maintenance sidecar failed during service lifetime"
            ) from failed
