"""Product-level managed unit plans independent of Linux process mechanisms."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from binnacle.deployment import units


@dataclass(frozen=True, slots=True)
class PlannedUnit:
    """A reviewed unit write plan, not permission to mutate host services."""

    path: Path
    spec: units.UnitSpec
    write: units.WritePlan

    @property
    def name(self) -> str:
        return self.spec.name


class UnitProvisioner(Protocol):
    """Existing CLI provisioning dependency, injected at host composition."""

    backup_dir: Path

    def unit_path(self, service: str) -> Path: ...

    def plan_unit(
        self, spec: units.UnitSpec, *, adopt: bool = False
    ) -> PlannedUnit: ...

    def plan_server_jobs(
        self,
        mode: str,
        repo: Path | None,
        host: str,
        port: int,
        *,
        adopt: bool = False,
    ) -> list[PlannedUnit]: ...

    def plan_server(
        self, mode: str, repo: Path | None, host: str, port: int
    ) -> PlannedUnit: ...

    def write_unit(self, planned: PlannedUnit) -> Path | None: ...

    def current_marker(self, service: str) -> units.Marker | None: ...

    def reload_definitions(self) -> object: ...

    def enable_now(self, service: str) -> object: ...

    def enable_persistence(self) -> object: ...

    def systemctl(
        self, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]: ...

    def inspect_persistence(self, *, user: str | None = None) -> object: ...
