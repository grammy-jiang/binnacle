"""Linux systemd user-service inspection for the G4 service contracts."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from binnacle.service_lifecycle_contracts import ManagedServiceStatus

_SMOKE_INSPECTION_TIMEOUT_S = 10.0
_CGROUP_FS = Path("/sys/fs/cgroup")
_PROC_ROOT = Path("/proc")
_RSS = re.compile(r"^VmRSS:\s+(\d+)\s+kB", re.MULTILINE)


def _integer(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


class SystemdUserServices:
    """Semantic inspection backed by systemd, procfs and cgroup v2."""

    def status(self, service: str) -> ManagedServiceStatus:
        state_proc = subprocess.run(
            ["systemctl", "--user", "is-active", service],
            capture_output=True,
            text=True,
            check=False,
        )
        state = state_proc.stdout.strip() or "unknown"
        props = subprocess.run(
            [
                "systemctl",
                "--user",
                "show",
                service,
                "-p",
                "MainPID",
                "-p",
                "NRestarts",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        values = {}
        for line in props.stdout.splitlines():
            key, sep, value = line.partition("=")
            if sep:
                values[key] = value
        pid = _integer(values.get("MainPID", ""))
        restarts = _integer(values.get("NRestarts", ""))
        return ManagedServiceStatus(
            state=state,
            main_pid=pid if pid is not None and pid > 0 else None,
            restart_count=restarts,
        )

    def _main_environ(self, service: str) -> tuple[int | None, bytes | None]:
        status = self.status(service)
        if status.state != "active":
            return None, None
        pid = status.main_pid
        if pid is None:
            return None, None
        try:
            return pid, (_PROC_ROOT / str(pid) / "environ").read_bytes()
        except OSError:
            return pid, None

    def main_process_has_environment(
        self, service: str, name: str, value: str
    ) -> bool | None:
        _, raw = self._main_environ(service)
        if raw is None:
            return None
        marker = f"{name}={value}".encode()
        return marker in raw.split(b"\0")

    def main_process_path(self, service: str) -> str | None:
        _, raw = self._main_environ(service)
        if raw is None:
            return None
        prefix = b"PATH="
        for item in raw.split(b"\0"):
            if item.startswith(prefix):
                return item[len(prefix) :].decode(errors="replace")
        return ""

    def _show_value(
        self,
        service: str,
        prop: str,
        *,
        timestamp_us: bool = False,
    ) -> str:
        argv = ["systemctl", "--user", "show", service, "-p", prop]
        argv += ["--value"]
        if timestamp_us:
            argv += ["--timestamp=us"]
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                check=False,
                timeout=_SMOKE_INSPECTION_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return proc.stdout.strip() if proc.returncode == 0 else ""

    def rss_kb(self, service: str) -> float | None:
        cgroup = self._show_value(service, "ControlGroup")
        if not cgroup:
            return None
        total = 0
        try:
            procs = _CGROUP_FS / cgroup.lstrip("/") / "cgroup.procs"
            for pid in procs.read_text().split():
                status = (_PROC_ROOT / pid / "status").read_text()
                match = _RSS.search(status)
                total += int(match.group(1)) if match else 0
        except OSError:
            return None
        return float(total) or None

    def started_at_epoch(self, service: str) -> float | None:
        stamp = self._show_value(
            service,
            "ExecMainStartTimestamp",
            timestamp_us=True,
        )
        if not stamp:
            return None
        try:
            proc = subprocess.run(
                ["date", "-d", stamp, "+%s.%N"],
                capture_output=True,
                text=True,
                check=False,
                timeout=_SMOKE_INSPECTION_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            return None
        try:
            return float(proc.stdout.strip())
        except ValueError:
            return None
