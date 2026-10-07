"""Platform-neutral managed-service inspection and control contracts."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ManagedServiceStatus:
    """Portable service facts used by generic orchestration and diagnostics."""

    state: str
    main_pid: int | None = None
    restart_count: int | None = None


@dataclass(frozen=True, slots=True)
class ServiceAction:
    """Result of a managed-service mutation."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    launch_error: str | None = None


class ManagedServiceInspector(Protocol):
    """Read-only service facts; no arbitrary platform-property escape hatch."""

    def status(self, service: str) -> ManagedServiceStatus: ...

    def started_at_epoch(self, service: str) -> float | None: ...

    def rss_kb(self, service: str) -> float | None: ...

    def main_process_has_environment(
        self, service: str, name: str, value: str
    ) -> bool | None: ...

    def main_process_path(self, service: str) -> str | None: ...


class ManagedServiceController(Protocol):
    """Portable mutation surface; restart is intentionally the only operation."""

    def restart(
        self, service: str, *, timeout: float | None = None
    ) -> ServiceAction: ...
