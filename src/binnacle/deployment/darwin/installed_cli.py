"""Thin CLI adapter for the installed macOS MCP LaunchDaemon.

The launchd transaction is in installed_mode; no systemd commands are used.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from binnacle.deployment.darwin.installed_mode import (
    DarwinInstalledMcpMode,
    InstalledMcpModeError,
)


class MacInstalledCLI:
    def __init__(self, controller: DarwinInstalledMcpMode | None = None) -> None:
        self.controller = controller or DarwinInstalledMcpMode()

    def setup(
        self,
        *,
        dev: Path | None,
        port: int,
        dry_run: bool,
        adopt: bool,
        force: bool = False,
    ) -> None:
        """Update a known installed service; never create an unknown root daemon."""
        try:
            mode: Literal["dev", "prod"] = "dev" if dev is not None else "prod"
            plan = self.controller.plan(mode, repo=dev, port=port)
            print(self.controller.preview(plan))
            if dry_run:
                print("dry run: nothing was changed.")
                return
            # --adopt never bypasses verified label/ownership/argv checks.
            _ = adopt
            print(self.controller.apply(plan, force=force))
        except InstalledMcpModeError as exc:
            print(str(exc))
            raise SystemExit(1) from None

    def mode(
        self,
        *,
        target: Literal["dev", "prod", "status"],
        repo: Path | None,
        force: bool,
    ) -> None:
        """Inspect or switch a recognized installed daemon with rollback."""
        try:
            if target == "status":
                print(self.controller.status())
                return
            plan = self.controller.plan(target, repo=repo)
            print(self.controller.preview(plan))
            print(self.controller.apply(plan, force=force))
        except InstalledMcpModeError as exc:
            print(str(exc))
            raise SystemExit(1) from None
