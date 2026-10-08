"""Linux systemd unit-definition diagnostic adapter."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import cast

Run = Callable[..., subprocess.CompletedProcess[str]]


def unit_property(service: str, prop: str, *, run: Run | None = None) -> str:
    """Read one systemd unit-definition property with the baseline unbounded wait."""

    runner = cast(Run, run or subprocess.run)
    try:
        proc = runner(
            ["systemctl", "--user", "show", service, "-p", prop, "--value"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""
