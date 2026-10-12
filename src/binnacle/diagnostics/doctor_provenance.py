"""Runtime provenance, ripgrep pin and start-up import checks for binnacle doctor.

E1-a4: a server or job manager whose required module fails to import exits
``EX_STARTUP_IMPORT`` and leaves a durable record (``binnacle.startup_imports``);
a clean start removes it. Under systemd ``Restart=`` or launchd ``KeepAlive``
such a process crash-loops; ``check_startup_imports`` keeps the cause visible.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

from binnacle.doctor_contracts import Check, fail, ok, warn
from binnacle.provenance import Provenance, runtime_provenance
from binnacle.startup_imports import record_dir


def check_provenance(value: Provenance | None = None) -> list[Check]:
    value = runtime_provenance() if value is None else value
    return [
        ok(
            "version",
            f"package={value.package_version} revision={value.revision}",
        )
    ]


PINNED_RG_VERSION = "15.2.0"

_VERSION_RE = re.compile(r"^ripgrep (\d+\.\d+\.\d+)")


def _rg_version(rg_bin: str) -> tuple[str, str | None]:
    path = shutil.which(rg_bin)
    if path is None:
        return rg_bin, None
    try:
        out = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return path, None
    match = _VERSION_RE.match(out)
    return path, match.group(1) if match else None


def check_rg_version(rg_bin: str, pinned: str = PINNED_RG_VERSION) -> list[Check]:
    """Report the ripgrep in use; WARN when it differs from the pin."""
    path, version = _rg_version(rg_bin)
    if version is None:
        return [
            warn(
                "ripgrep",
                f"cannot read the version of {rg_bin!r} ({path})",
                "set rg_bin to a user-level binary of the pinned version",
            )
        ]
    detail = f"{path} version={version} pinned={pinned}"
    if version != pinned:
        return [
            warn(
                "ripgrep",
                f"{detail}: differs from the pin",
                "set rg_bin to a user-level binary of the pinned version",
            )
        ]
    return [ok("ripgrep", detail)]


def check_startup_imports(directory: Path | None = None) -> list[Check]:
    root = record_dir() if directory is None else directory
    records = sorted(root.glob("*.json")) if root.is_dir() else []
    if not records:
        return [ok("startup", "no start-up import failure recorded")]
    checks = []
    for path in records:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            detail = (
                f"{data['process']} failed to import {data['module']} "
                f"({data['error_class']} at {data['where']}) at {data['time']} "
                f"pid={data['pid']} exit={data['exit_code']}"
            )
        except (OSError, ValueError, KeyError, TypeError):
            detail = f"unreadable start-up import record {path.name}"
        checks.append(
            fail(
                "startup",
                detail,
                "fix the module and restart; a clean start clears this record",
            )
        )
    return checks
