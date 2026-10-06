"""Linux/systemd provisioning owned outside generic CLI orchestration."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from binnacle import units
from binnacle.job_manager_unit import (
    job_manager_params,
    job_manager_unit_spec,
)
from binnacle.server_unit import server_params, server_unit_spec

UNIT_DIR = units.UNIT_DIR
DEFAULT_BACKUP_DIR = Path.home() / ".local" / "state" / "binnacle" / "unit-backups"
Run = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True, slots=True)
class PersistenceInspection:
    enabled: bool | None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PlannedUnit:
    """One Linux unit-file plan with its path and rendered provenance."""

    path: Path
    spec: units.UnitSpec
    write: units.WritePlan

    @property
    def name(self) -> str:
        return self.spec.name


class LinuxServiceProvisioner:
    """Systemd definition/provisioning mechanics for the current user."""

    def __init__(
        self,
        *,
        unit_dir: Path = UNIT_DIR,
        backup_dir: Path = DEFAULT_BACKUP_DIR,
        run: Run | None = None,
    ) -> None:
        self.unit_dir = unit_dir
        self.backup_dir = backup_dir
        self._run: Run = cast(Run, run or subprocess.run)

    def unit_path(self, service: str) -> Path:
        return self.unit_dir / service

    def plan_unit(self, spec: units.UnitSpec, *, adopt: bool = False) -> PlannedUnit:
        path = self.unit_path(spec.name)
        return PlannedUnit(path, spec, units.plan_write(path, spec, adopt=adopt))

    def plan_server_jobs(
        self,
        mode: str,
        repo: Path | None,
        host: str,
        port: int,
        *,
        adopt: bool = False,
    ) -> list[PlannedUnit]:
        return [
            self.plan_unit(
                job_manager_unit_spec(job_manager_params(mode, repo)),
                adopt=adopt,
            ),
            self.plan_unit(
                server_unit_spec(server_params(mode, repo, host, port)),
                adopt=adopt,
            ),
        ]

    def plan_server(
        self,
        mode: str,
        repo: Path | None,
        host: str,
        port: int,
    ) -> PlannedUnit:
        return self.plan_unit(server_unit_spec(server_params(mode, repo, host, port)))

    def write_unit(self, planned: PlannedUnit) -> Path | None:
        return units.write_unit(planned.path, planned.write, self.backup_dir)

    def current_marker(self, service: str) -> units.Marker | None:
        path = self.unit_path(service)
        if not path.exists():
            return None
        return units.read_marker(path.read_text(encoding="utf-8"))

    def systemctl(
        self, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return self._run(
            ["systemctl", "--user", *args],
            capture_output=True,
            text=True,
            check=check,
        )

    def reload_definitions(self) -> subprocess.CompletedProcess[str]:
        return self.systemctl("daemon-reload")

    def enable_now(self, service: str) -> subprocess.CompletedProcess[str]:
        return self.systemctl("enable", "--now", service)

    def enable_persistence(self) -> subprocess.CompletedProcess[str]:
        return self._run(["loginctl", "enable-linger"], check=True)

    def inspect_persistence(
        self,
        *,
        user: str | None = None,
        timeout: float | None = None,
    ) -> PersistenceInspection:
        who = user or os.environ.get("USER", "")
        kwargs: dict[str, object] = {
            "capture_output": True,
            "text": True,
            "check": False,
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        try:
            proc = self._run(
                ["loginctl", "show-user", who, "-p", "Linger", "--value"],
                **kwargs,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return PersistenceInspection(None, error=str(exc))
        if proc.returncode != 0:
            return PersistenceInspection(None)
        return PersistenceInspection(proc.stdout.strip().split("=", 1)[-1] == "yes")
