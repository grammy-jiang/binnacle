"""Installed production LaunchDaemons (``system/com.binnacle.*``) for deploy gates.

The deploy gate names services by their Linux unit names; ``binnacle-mcp.service``
is the LaunchDaemon ``com.binnacle.mcp``. Reads need no privilege. A restart is
``sudo -n launchctl kickstart -k`` and then waits for a new running process.
Process environments are not read on Darwin, so those facts stay unknown.
"""

from __future__ import annotations

import re
import subprocess
import time

from binnacle.platform.contracts.service_lifecycle_contracts import (
    ManagedServiceStatus,
    ServiceAction,
)
from binnacle.platform.darwin.process_authority import _process_records

_UNIT = re.compile(r"^binnacle-([a-z0-9][a-z0-9-]*)\.service$")
_INSPECT_TIMEOUT_S = 10.0


def launchd_label(service: str) -> str:
    """``binnacle-<name>.service`` -> ``com.binnacle.<name>``."""
    match = _UNIT.match(service)
    if match is None:
        raise ValueError(f"not a binnacle service name: {service!r}")
    return f"com.binnacle.{match[1]}"


def _text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


def _run(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


class LaunchdSystemServices:
    """Inspector and controller for the installed ``system/`` LaunchDaemons."""

    def __init__(self, *, poll_s: float = 0.5) -> None:
        self._poll_s = poll_s

    def status(self, service: str) -> ManagedServiceStatus:
        target = f"system/{launchd_label(service)}"
        proc = _run(["/bin/launchctl", "print", target], _INSPECT_TIMEOUT_S)
        if proc is None:
            return ManagedServiceStatus("unknown")
        if proc.returncode == 113 and "Could not find service" in proc.stderr:
            return ManagedServiceStatus("inactive")
        # Only top-level (one-tab) facts; nested blocks describe other things.
        state = re.search(r"^\tstate = (.+)$", proc.stdout, re.MULTILINE)
        if proc.returncode or state is None:
            return ManagedServiceStatus("unknown")
        pid = re.search(r"^\tpid = ([1-9][0-9]*)$", proc.stdout, re.MULTILINE)
        runs = re.search(r"^\truns = ([0-9]+)$", proc.stdout, re.MULTILINE)
        return ManagedServiceStatus(
            "active" if state[1] == "running" else "inactive",
            int(pid[1]) if pid else None,
            max(0, int(runs[1]) - 1) if runs else None,
        )

    def _main_pid(self, service: str) -> int | None:
        status = self.status(service)
        return status.main_pid if status.state == "active" else None

    def started_at_epoch(self, service: str) -> float | None:
        pid = self._main_pid(service)
        if pid is None:
            return None
        try:
            records = _process_records(1, pid)
        except OSError:
            return None
        if len(records) != 1:
            return None
        seconds, micros = records[0].birth
        return seconds + micros / 1_000_000

    def rss_kb(self, service: str) -> float | None:
        """RSS (kB) of the main process and all of its descendants."""
        pid = self._main_pid(service)
        if pid is None:
            return None
        proc = _run(["/bin/ps", "-A", "-o", "pid=,ppid=,rss="], _INSPECT_TIMEOUT_S)
        if proc is None or proc.returncode:
            return None
        children: dict[int, list[int]] = {}
        rss: dict[int, int] = {}
        for line in proc.stdout.splitlines():
            fields = line.split()
            if len(fields) == 3 and all(f.isdigit() for f in fields):
                child, parent, kb = map(int, fields)
                children.setdefault(parent, []).append(child)
                rss[child] = kb
        if pid not in rss:
            return None
        total, todo = 0, [pid]
        while todo:
            current = todo.pop()
            total += rss.get(current, 0)
            todo.extend(children.get(current, ()))
        return float(total) or None

    def main_process_has_environment(
        self, service: str, name: str, value: str
    ) -> bool | None:
        return None

    def main_process_path(self, service: str) -> str | None:
        return None

    def restart(self, service: str, *, timeout: float | None = None) -> ServiceAction:
        budget = 90.0 if timeout is None else timeout
        deadline = time.monotonic() + budget
        before = self._main_pid(service)
        argv = ["/usr/bin/sudo", "-n", "/bin/launchctl", "kickstart", "-k"]
        argv.append(f"system/{launchd_label(service)}")
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=budget, check=False
            )
        except subprocess.TimeoutExpired as exc:
            return ServiceAction(
                124, _text(exc.stdout), _text(exc.stderr), timed_out=True
            )
        except OSError as exc:
            return ServiceAction(127, stderr=str(exc), launch_error=str(exc))
        if proc.returncode:
            return ServiceAction(proc.returncode, proc.stdout, proc.stderr)
        while True:
            after = self._main_pid(service)
            if after is not None and after != before:
                return ServiceAction(0, proc.stdout, proc.stderr)
            if time.monotonic() >= deadline:
                return ServiceAction(
                    124,
                    proc.stdout,
                    f"no new running process after {budget:g} s",
                    timed_out=True,
                )
            time.sleep(self._poll_s)
