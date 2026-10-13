"""Read-only Binnacle reboot admission report for macOS and Linux hosts.

Do NOT reboot, restart, stop, disable, install or rotate anything.
Two independent questions are reported:
1. Does the service configuration appear prepared for an OS restart?
2. Is it safe to interrupt work *right now*? Unknown activity fails closed.

"ready" is a preflight candidate only, not proof that hardware will recover
from an actual power cycle. Keep a maintenance window for real reboot tests.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import re
import stat
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

_MAC_SERVICES = ("mcp", "jobs", "tunnel", "service-watchdog", "resource-monitor")
_LINUX_CORE = ("mcp", "jobs", "tunnel", "resource-monitor")
_DEV_AGENTS = frozenset(("claude", "codex", "pytest", "claude-code"))
# Local coding agents are not Binnacle-owned jobs. External inspection is
# available as opt-in diagnostics only; it must not silently veto a check.


@dataclass(frozen=True)
class Readiness:
    host: str
    boot_checks: dict[str, bool]
    blocker_reasons: tuple[str, ...]

    @property
    def boot_ready(self) -> bool:
        return bool(self.boot_checks) and all(self.boot_checks.values())

    @property
    def reboot_now_candidate(self) -> bool:
        return self.boot_ready and not self.blocker_reasons

    def report(self) -> dict[str, object]:
        return {
            **asdict(self),
            "boot_ready": self.boot_ready,
            "reboot_now_candidate": self.reboot_now_candidate,
            "warning": (
                "This is a static preflight only; it does not authorize a "
                "live hardware reboot or prove that interrupted work is recoverable."
            ),
        }


def _run(argv: list[str]) -> str | None:
    """Only these fixed read-only programs are permitted."""
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def _mac_plist_ok(path: Path, *, label: str, expected_uid: int = 0) -> bool:
    try:
        meta = path.lstat()
        if (
            not stat.S_ISREG(meta.st_mode)
            or meta.st_uid != expected_uid
            or meta.st_mode & 0o022
        ):
            return False
        definition = plistlib.loads(path.read_bytes())
        if not isinstance(definition, dict):
            return False
        argv = definition.get("ProgramArguments")
        if not isinstance(argv, list) or not argv:
            return False
        executable = argv[0]
        return (
            definition.get("Label") == label
            and definition.get("RunAtLoad") is True
            and bool(definition.get("KeepAlive"))
            and isinstance(executable, str)
            and Path(executable).is_absolute()
            and os.access(executable, os.X_OK)
            and definition.get("Umask") == 0o077
        )
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
        return False


def _mac_boot_checks(root: Path = Path("/Library/LaunchDaemons")) -> dict[str, bool]:
    checks = {}
    for service in _MAC_SERVICES:
        label = f"com.binnacle.{service}"
        checks[f"{service}.boot_definition"] = _mac_plist_ok(
            root / f"{label}.plist", label=label
        )
        status = _run(["/bin/launchctl", "print", f"system/{label}"])
        checks[f"{service}.currently_running"] = bool(
            status and re.search(r"^\s*state = running\s*$", status, re.MULTILINE)
        )
    return checks


def _linux_boot_checks() -> dict[str, bool]:
    services = list(_LINUX_CORE)
    watchdog = _run(["systemctl", "--user", "is-enabled", "binnacle-watchdog.service"])
    services.append("watchdog" if watchdog == "enabled\n" else "service-watchdog")
    checks: dict[str, bool] = {}
    linger = _run(["loginctl", "show-user", str(os.getuid()), "-p", "Linger"])
    checks["user_lingering_enabled"] = bool(linger and linger.strip() == "Linger=yes")
    for name in services:
        label = f"binnacle-{name}.service"
        enabled = _run(["systemctl", "--user", "is-enabled", label])
        active = _run(["systemctl", "--user", "is-active", label])
        checks[f"{name}.enabled"] = bool(enabled and enabled.strip() == "enabled")
        checks[f"{name}.active"] = bool(active and active.strip() == "active")
    return checks


def _developer_processes() -> int | None:
    """Only process basenames are consulted. No command arguments or secrets."""
    output = _run(["ps", "-A", "-o", "comm="])
    if output is None:
        return None
    count = 0
    for entry in output.splitlines():
        executable = Path(entry.strip()).name.lower()
        if executable in _DEV_AGENTS:
            count += 1
    return count


def _job_activity(host: str) -> int | None:
    try:
        from binnacle.companions.service_watchdog_safety import current_job_activity
        from binnacle.config import get_settings

        return current_job_activity(get_settings().jobs.dir, host=host)
    except (OSError, RuntimeError, TypeError, ValueError, AttributeError):
        return None


def inspect(
    *, system: str | None = None, check_external_processes: bool = False
) -> Readiness:
    platform_name = platform.system() if system is None else system
    if platform_name not in {"Darwin", "Linux"}:
        return Readiness(platform_name, {"supported_host": False}, ("unknown_host",))
    host = "darwin" if platform_name == "Darwin" else "linux"
    checks = _mac_boot_checks() if host == "darwin" else _linux_boot_checks()
    blockers = []
    activity = _job_activity(host)
    if activity is None:
        blockers.append("job_activity_unknown")
    elif activity > 0:
        blockers.append("jobs_still_active")
    # Binnacle job activity remains authoritative; local Claude/Codex
    # processes may be long-lived, idle development agents unrelated to
    # this service. Their presence must not block normal admission.
    if check_external_processes:
        agents = _developer_processes()
        if agents is None:
            blockers.append("developer_process_scan_unavailable")
        elif agents > 0:
            blockers.append("other_development_processes_running")
    return Readiness(host, checks, tuple(blockers))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable summary")
    parser.add_argument(
        "--check-external-processes",
        action="store_true",
        help="opt in to checking unrelated local development agents",
    )
    args = parser.parse_args(argv)
    status = inspect(check_external_processes=args.check_external_processes)
    if args.json:
        print(json.dumps(status.report(), sort_keys=True))
    else:
        print(
            f"boot_ready={status.boot_ready} "
            f"reboot_now_candidate={status.reboot_now_candidate}"
        )
        for name, ok in status.boot_checks.items():
            print(f"  {name}: {'ok' if ok else 'UNVERIFIED'}")
        for blocker in status.blocker_reasons:
            print(f"  blocker: {blocker}")
        print("This is a static check, not a command to reboot.")
    return 0 if status.reboot_now_candidate else 2


if __name__ == "__main__":
    raise SystemExit(main())
