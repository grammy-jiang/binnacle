"""Linux/XDG runtime-path conventions."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from binnacle.runtime_path_contracts import RuntimePaths


def resolve_runtime_paths(
    environ: Mapping[str, str] | None = None,
    *,
    uid: int | None = None,
) -> RuntimePaths:
    """Resolve Binnacle's private runtime directory and manager socket.

    Linux preserves the existing convention exactly: prefer XDG_RUNTIME_DIR;
    otherwise use /run/user/<uid>, then append binnacle/jobs.sock.
    """

    env = os.environ if environ is None else environ
    runtime = env.get("XDG_RUNTIME_DIR")
    host_base = (
        Path(runtime)
        if runtime
        else Path(f"/run/user/{os.getuid() if uid is None else uid}")
    )
    binnacle_runtime_dir = host_base / "binnacle"
    return RuntimePaths(
        binnacle_runtime_dir=binnacle_runtime_dir,
        jobs_socket=binnacle_runtime_dir / "jobs.sock",
    )
