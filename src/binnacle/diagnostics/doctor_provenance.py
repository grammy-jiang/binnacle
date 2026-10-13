"""Runtime provenance, ripgrep pin and start-up import checks for binnacle doctor.

E1-a4: a server or job manager whose required module fails to import exits
``EX_STARTUP_IMPORT`` and leaves a durable record (``binnacle.startup_imports``);
a clean start removes it. Under systemd ``Restart=`` or launchd ``KeepAlive``
such a process crash-loops; ``check_startup_imports`` keeps the cause visible.
E1-a5: it shows the record's age and revision. A record of an older revision
than the running checkout is STALE (WARN) only when BOTH revisions are
validated Git SHA identifiers. Current, missing or unknown provenance is FAIL.
"""

import calendar
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from binnacle.config import get_settings
from binnacle.doctor_contracts import Check, fail, ok, warn
from binnacle.provenance import Provenance, runtime_provenance
from binnacle.startup_imports import record_dir, state_root_of


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


def _age(stamp: str, now: float) -> str:
    try:
        seconds = max(
            0, int(now - calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")))
        )
    except (ValueError, OverflowError):
        return "age=?"
    return f"age={seconds}s"


def _known_git_revision(value: object) -> bool:
    """Only Git revisions can establish a different/old recorded checkout.

    An early failure may be unable to import provenance; its revision is
    unknown, not evidence of a stale record from an earlier deployment.
    """
    return (
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{12,40}(?:\+dirty)?", value) is not None
    )


def check_startup_imports(
    directory: Path | None = None,
    *,
    revision: str | None = None,
    now: float | None = None,
) -> list[Check]:
    """FAIL for current/unknown provenance; WARN only for a different known SHA."""
    root = (
        record_dir(state_root_of(get_settings().jobs.dir))
        if directory is None
        else directory
    )
    records = sorted(root.glob("*.json")) if root.is_dir() else []
    if not records:
        return [ok("startup", "no start-up import failure recorded")]
    current = runtime_provenance().revision if revision is None else revision
    seen_at = time.time() if now is None else now
    checks = []
    for path in records:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            recorded = data.get("revision")
            detail = (
                f"{data['process']} failed to import {data['module']} "
                f"({data['error_class']} at {data['where']}) at {data['time']} "
                f"{_age(data['time'], seen_at)} revision={recorded or '?'}"
            )
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            checks.append(
                fail(
                    "startup",
                    f"unreadable start-up import record {path.name}",
                    "fix the module and restart; a clean start clears this record",
                )
            )
            continue
        if (
            _known_git_revision(recorded)
            and _known_git_revision(current)
            and recorded != current
        ):
            checks.append(
                warn(
                    "startup",
                    f"STALE: {detail} (running revision={current})",
                    "a record from an older revision; a clean start clears it",
                )
            )
        else:
            checks.append(
                fail(
                    "startup",
                    detail,
                    "fix the module and restart; a clean start clears this record",
                )
            )
    return checks
