"""Read-only, low-frequency Darwin host resource telemetry companion.

Darwin does not expose Linux PSI; collect named native metrics instead, with
no process enumeration, per-job attribution, network operations or recovery.
An unavailable metric is omitted and logged, never guessed.
"""

from __future__ import annotations

import argparse
import logging
import os
import platform
import plistlib
import re
import subprocess
import time
from pathlib import Path

from binnacle.companions.darwin_log_privacy import MIN_DISK_FREE_BYTES

log = logging.getLogger("binnacle.resource_monitor")
_VM_PAGE_SIZE = re.compile(r"page size of (\d+) bytes")
_VM_PAGE = re.compile(
    r"^Pages (free|active|inactive|speculative|wired down):\s*(\d+)\.", re.MULTILINE
)
_MEMORY_FREE = re.compile(r"System-wide memory free percentage:\s*(\d+)%")
MAC_LABEL = "com.binnacle.resource-monitor"


def _read_native(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=3
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def parse_vm_stat(text: str) -> dict[str, int]:
    """Each reported page count is labelled; do not invent available memory."""
    header = _VM_PAGE_SIZE.search(text)
    if not header:
        return {}
    out = {"vm_page_size_bytes": int(header.group(1))}
    names = {
        "free": "vm_pages_free",
        "active": "vm_pages_active",
        "inactive": "vm_pages_inactive",
        "speculative": "vm_pages_speculative",
        "wired down": "vm_pages_wired",
    }
    for kind, count in _VM_PAGE.findall(text):
        out[names[kind]] = int(count)
    return out


def snapshot(home: Path | None = None) -> dict[str, int | float]:
    """Best-effort read of system load, memory, and free space."""
    data: dict[str, int | float] = {}
    try:
        one, five, fifteen = os.getloadavg()
        data.update(load1=round(one, 2), load5=round(five, 2), load15=round(fifteen, 2))
    except OSError:
        pass
    cpus = os.cpu_count()
    if cpus is not None and cpus > 0:
        data["cpu_count"] = cpus
    try:
        disk = os.statvfs(home or Path.home())
        data["disk_free_bytes"] = disk.f_bavail * disk.f_frsize
        data["disk_total_bytes"] = disk.f_blocks * disk.f_frsize
    except OSError:
        pass
    stats = _read_native(["/usr/bin/vm_stat"])
    if stats is not None:
        data.update(parse_vm_stat(stats))
    pressure = _read_native(["/usr/bin/memory_pressure", "-Q"])
    if pressure is not None:
        found = _MEMORY_FREE.search(pressure)
        if found:
            free_percent = int(found.group(1))
            if 0 <= free_percent <= 100:
                data["memory_pressure_free_percent"] = free_percent
    memory_total = _read_native(["/usr/sbin/sysctl", "-n", "hw.memsize"])
    if memory_total is not None:
        try:
            size = int(memory_total.strip())
            if size > 0:
                data["memory_total_bytes"] = size
        except ValueError:
            pass
    return data


def emit_snapshot(*, reader=snapshot) -> dict[str, int | float]:
    data = reader()
    if not data:
        log.warning("event=resource_snapshot_unavailable host=darwin")
    else:
        rendered = " ".join(f"{key}={value}" for key, value in sorted(data.items()))
        log.info("event=resource_snapshot host=darwin %s", rendered)
        free_bytes = data.get("disk_free_bytes")
        if (
            isinstance(free_bytes, (int, float))
            and 0 <= free_bytes < MIN_DISK_FREE_BYTES
        ):
            log.warning(
                "event=resource_disk_space_low host=darwin free_bytes=%d "
                "keep_free_bytes=%d action=maintenance_required",
                int(free_bytes),
                MIN_DISK_FREE_BYTES,
            )
    return data


def render_launchd_plist(
    *,
    python: Path,
    home: Path,
    username: str,
    group: str = "staff",
    interval_s: int = 60,
) -> bytes:
    """Render only; deployment is a separate, reviewed privileged step."""
    if (
        not python.is_absolute()
        or not home.is_absolute()
        or not username.replace("-", "").replace("_", "").isalnum()
        or not username
        or not group.replace("-", "").replace("_", "").isalnum()
        or not group
        or not 30 <= interval_s <= 3600
    ):
        raise ValueError("invalid Darwin resource monitor plan")
    logroot = home / "Library/Logs/binnacle"
    return plistlib.dumps(
        {
            "Label": MAC_LABEL,
            "ProgramArguments": [
                str(python),
                "-m",
                "binnacle.companions.resource_monitor_darwin",
                "--interval",
                str(interval_s),
            ],
            "UserName": username,
            "GroupName": group,
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},
            "ThrottleInterval": 15,
            "Umask": 0o077,
            "StandardOutPath": str(logroot / "resource-monitor.stdout.log"),
            "StandardErrorPath": str(logroot / "resource-monitor.stderr.log"),
            "EnvironmentVariables": {
                "HOME": str(home),
                "PYTHONUNBUFFERED": "1",
                "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
            },
        },
        sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args(argv)
    if platform.system() != "Darwin" or not 30 <= args.interval <= 3600:
        parser.error("Darwin only; interval must be 30–3600 seconds")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d %(levelname)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    from binnacle.companions.darwin_log_privacy import (
        harden_private_logs,
        logs_nearing_rotation,
    )

    log_root = Path.home() / "Library/Logs/binnacle"
    notified_large: set[str] = set()
    while True:
        try:
            tightened = harden_private_logs(log_root)
            if tightened:
                log.warning(
                    "event=resource_log_permissions_hardened count=%d",
                    len(tightened),
                )
        except RuntimeError:
            log.warning("event=resource_log_privacy_unverified")
        try:
            large = logs_nearing_rotation(log_root)
            current = {name for name, _ in large}
            for name, size in large:
                if name not in notified_large:
                    log.warning(
                        "event=resource_log_rotation_maintenance_needed "
                        "file=%s bytes=%d action=quiet_window_required",
                        name,
                        size,
                    )
            notified_large = current
        except RuntimeError:
            log.warning("event=resource_log_rotation_check_unavailable")
        emit_snapshot()
        if args.once:
            return 0
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
