"""Runtime provenance and ripgrep pin checks for binnacle doctor."""

import re
import shutil
import subprocess

from binnacle.doctor_contracts import Check, ok, warn
from binnacle.provenance import Provenance, runtime_provenance


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
