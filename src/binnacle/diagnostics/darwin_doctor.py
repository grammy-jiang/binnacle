"""Read-only macOS LaunchDaemon diagnostics for the Binnacle doctor CLI.

Do not use Linux service provisioning. Audit installed root-owned launchd
services, authenticated native job management, MCP connectivity and startup
failure records. Never restart, bootstrap, reconfigure or repair services.
"""

from __future__ import annotations

import os
import plistlib
import re
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from binnacle.config import get_settings
from binnacle.diagnostics import doctor as shared
from binnacle.doctor_contracts import Check, fail, ok, warn
from binnacle.platform.composition import create_job_client, create_runtime_paths
from binnacle.provenance import runtime_provenance

_LAUNCHD_SERVICES = (
    "mcp",
    "jobs",
    "tunnel",
    "service-watchdog",
    "resource-monitor",
)


def _launchd_status(label: str) -> str | None:
    """Observe, never mutate the launchd system domain; no shell."""
    try:
        proc = subprocess.run(
            ["/bin/launchctl", "print", f"system/{label}"],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def check_launchd(
    root: Path = Path("/Library/LaunchDaemons"),
    *,
    expected_uid: int = 0,
    status: Callable[[str], str | None] = _launchd_status,
) -> tuple[list[Check], dict[str, int]]:
    """Check boot definitions and current service PIDs without leaking args.

    The tunnel plist can contain secrets. Do not print any plist body.
    """
    checks: list[Check] = []
    running: dict[str, int] = {}
    for svc in _LAUNCHD_SERVICES:
        label = f"com.binnacle.{svc}"
        path = root / f"{label}.plist"
        try:
            st = path.lstat()
            if (
                not stat.S_ISREG(st.st_mode)
                or st.st_uid != expected_uid
                or st.st_nlink != 1
                or st.st_mode & 0o022
            ):
                raise ValueError("unsafe file type, ownership or mode")
            definition = plistlib.loads(path.read_bytes())
            if not isinstance(definition, dict):
                raise TypeError("invalid plist")
            argv = definition.get("ProgramArguments")
            if not (
                definition.get("Label") == label
                and definition.get("RunAtLoad") is True
                and bool(definition.get("KeepAlive"))
                and definition.get("Umask") == 0o077
                and isinstance(argv, list)
                and bool(argv)
                and isinstance(argv[0], str)
                and Path(argv[0]).is_absolute()
                and os.access(argv[0], os.X_OK)
            ):
                raise ValueError("unsafe or incomplete boot definition")
        except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
            checks.append(
                fail(
                    "launchd",
                    f"{label}: installed root-owned boot definition invalid",
                    "review launchd plist before any restart",
                )
            )
        else:
            checks.append(ok("launchd", f"{label}: safe boot definition"))
        try:
            output = status(label)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            output = None
        match = re.search(r"^\s*pid = ([0-9]+)\s*$", output or "", re.MULTILINE)
        active = re.search(r"^\s*state = running\s*$", output or "", re.MULTILINE)
        pid = int(match.group(1)) if match else 0
        if active and pid > 0:
            running[svc] = pid
            checks.append(ok("launchd", f"{label}: running pid={pid}"))
        else:
            checks.append(
                fail(
                    "launchd",
                    f"{label}: not verifiably running",
                    "review the live launchd status and owned jobs",
                )
            )
    return checks, running


def check_native_job_manager(
    expected_revision: str,
    running_pids: dict[str, int],
    *,
    ping: Callable[[Path], dict[str, Any]] | None = None,
) -> list[Check]:
    """Use authenticated Darwin IPC, not Linux plaintext job RPC."""
    if "jobs" not in running_pids:
        return [fail("jobs-service", "com.binnacle.jobs has no verified live PID")]
    try:
        settings = get_settings()
        socket_path = settings.jobs.socket_path or create_runtime_paths().jobs_socket
        responder = ping if ping is not None else create_job_client().ping
        reply = responder(socket_path)
        if (
            not isinstance(reply, dict)
            or reply.get("ok") is not True
            or type(reply.get("pid")) is not int
            or reply["pid"] != running_pids["jobs"]
        ):
            raise ValueError("authenticated manager/launchd mismatch")
        revision = reply.get("revision")
        if (
            not isinstance(revision, str)
            or re.fullmatch(r"[0-9a-f]{12,40}", revision) is None
        ):
            raise ValueError("revision unavailable")
        if os.path.realpath(str(reply.get("jobs_dir", ""))) != os.path.realpath(
            str(settings.jobs.dir)
        ):
            raise ValueError("durable job root differs from configured root")
        running_jobs, unknown_jobs = (
            reply.get("running_jobs"),
            reply.get("unknown_jobs"),
        )
        if (
            type(running_jobs) is not int
            or running_jobs < 0
            or type(unknown_jobs) is not int
            or unknown_jobs < 0
        ):
            raise ValueError("activity counters unavailable")
    except (OSError, RuntimeError, ValueError, AttributeError, TypeError):
        return [
            fail(
                "jobs-service",
                "authenticated manager identity, revision or activity unverifiable",
                "do not upgrade/restart jobs while manager state is unknown",
            )
        ]
    checks = [
        ok(
            "jobs-service",
            f"authenticated pid={reply['pid']} revision={revision}; "
            f"{running_jobs} running, {unknown_jobs} unknown",
        )
    ]
    if re.fullmatch(r"[0-9a-f]{12,40}", expected_revision) is None:
        checks.append(
            fail(
                "jobs-service",
                "checkout Git revision not verifiably pinned",
                "verify current Git provenance before managed deployment",
            )
        )
    elif revision[:12] != expected_revision[:12]:
        checks.append(
            fail(
                "jobs-service",
                f"manager revision={revision} differs from checkout "
                f"{expected_revision[:12]}",
                "defer a managed switch until the J7 quiet gate allows it",
            )
        )
    if unknown_jobs:
        checks.append(
            warn(
                "jobs-service",
                f"{unknown_jobs} job(s) lack a confirmed terminal status",
                "inspect durable jobs; never assume they are idle",
            )
        )
    version, waitid = (
        reply.get("manager_python_version"),
        reply.get("manager_waitid_available"),
    )
    if version is not None or waitid is not None:
        try:
            parts = str(version).split(".")
            py = (int(parts[0]), int(parts[1]))
        except (ValueError, IndexError, TypeError):
            py = (0, 0)
        if len(str(version).split(".")) != 2 or py < (3, 13) or waitid is not True:
            checks.append(
                fail("jobs-python", "manager Python >=3.13 and waitid not established")
            )
        else:
            checks.append(ok("jobs-python", f"manager Python {version} and waitid"))
    return checks


def _append_safe(
    output: list[Check], group: str, fn: Callable[[], list[Check]]
) -> None:
    """A broken non-startup check must not erase startup-gate JSON evidence."""
    try:
        rows = fn()
        if not isinstance(rows, list) or not all(isinstance(c, Check) for c in rows):
            raise TypeError("invalid diagnostic result")
        output.extend(rows)
    except Exception as exc:  # noqa: BLE001 - diagnostic fail-closed JSON boundary
        output.append(fail(group, f"diagnostic unavailable ({type(exc).__name__})"))


def run_all(*, server_url: str, token_file: Path) -> list[Check]:
    """Read-only Darwin checks with portable shared JSON rendering."""
    checks: list[Check] = []
    # J7m-W3 requires an explicit startup check even when other checks fail.
    _append_safe(checks, "startup", shared.check_startup_imports)
    _append_safe(checks, "version", shared.check_provenance)
    _append_safe(checks, "config", shared.check_config)
    _append_safe(checks, "config", shared.check_config_keys)
    _append_safe(
        checks, "ripgrep", lambda: shared.check_rg_version(get_settings().rg_bin)
    )
    _append_safe(checks, "token", lambda: shared.check_token(token_file))
    try:
        launch_checks, pids = check_launchd()
        checks.extend(launch_checks)
    except Exception as exc:  # noqa: BLE001 - diagnostic fail-closed JSON boundary
        checks.append(
            fail("launchd", f"launchd inspection unavailable ({type(exc).__name__})")
        )
        pids = {}
    _append_safe(
        checks,
        "jobs-service",
        lambda: check_native_job_manager(runtime_provenance().revision, pids),
    )
    _append_safe(
        checks, "endpoint", lambda: shared.check_endpoint(server_url, token_file)
    )
    return checks
