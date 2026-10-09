"""Linux systemd/procfs unit inspection; no FastMCP or Binnacle policy imports."""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path


class LinuxUnitInspection:
    """Explicit Linux-only compatibility mechanics for historical unit APIs."""

    def resolve_executable(
        self,
        name: str,
        argv0: str | None = None,
        which: Callable[[str], str | None] | None = None,
    ) -> Path:
        finder = which or shutil.which
        candidate = finder(name) or argv0 or sys.argv[0]
        path = Path(os.path.abspath(Path(candidate).expanduser()))
        if not (path.is_file() and os.access(path, os.X_OK)):
            raise ValueError(
                f"cannot resolve the {name} executable from {candidate!r}; run setup "
                f"through the installed command, for example <venv>/bin/{name} setup"
            )
        return path

    def proc_cmdline(self, pid: int) -> list[str]:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        return [a.decode(errors="replace") for a in raw.split(b"\0") if a]

    def unit_property(
        self, unit: str, prop: str, run: Callable[..., object] | None = None
    ) -> str:
        if run is None:
            try:
                proc = subprocess.run(
                    ["systemctl", "--user", "show", unit, "-p", prop, "--value"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except OSError:
                return ""
            return proc.stdout.strip() if proc.returncode == 0 else ""
        result = run("show", unit, "-p", prop, "--value")
        return getattr(result, "stdout", "").strip()

    def exec_start_argv(self, value: str) -> list[str]:
        """Parse the Linux systemctl show ExecStart property, preserving legacy rules."""
        for part in value.strip().strip("{}").split(";"):
            part = part.strip()
            if part.startswith("argv[]="):
                return part[len("argv[]=") :].split()
        return []

    def inspect_process(
        self,
        unit: str,
        group: str,
        setup_hint: str,
        restart_hint: str,
        *,
        property_reader: Callable[[str, str], str],
        cmdline: Callable[[int], list[str]],
        parse_exec: Callable[[str], list[str]],
    ) -> list[tuple[str, str, str, str | None]]:
        """Return Linux-specific evidence; generic layer owns Check records."""
        argv = parse_exec(property_reader(unit, "ExecStart"))
        if not argv:
            reason = property_reader(unit, "LoadError")
            return [
                (
                    "fail",
                    group,
                    f"{unit} has no ExecStart" + (f": {reason}" if reason else ""),
                    setup_hint,
                )
            ]
        exe, shown = argv[0], " ".join(argv)
        if not (Path(exe).is_file() and os.access(exe, os.X_OK)):
            return [
                (
                    "fail",
                    group,
                    f"{unit} starts {exe}, which is missing or not executable",
                    setup_hint,
                )
            ]
        try:
            pid = int(property_reader(unit, "MainPID") or 0)
        except ValueError:
            pid = 0
        if pid <= 0:
            return [("ok", group, f"{unit} starts {shown}", None)]
        try:
            running = cmdline(pid)
        except OSError as exc:
            return [
                (
                    "warn",
                    group,
                    f"cannot read the command line of pid {pid}: {exc}",
                    None,
                )
            ]
        if running[-len(argv) :] == argv:
            return [
                ("ok", group, f"{unit} starts {shown}; pid {pid} is that command", None)
            ]
        return [
            (
                "warn",
                group,
                (
                    f"pid {pid} was started as \x60{' '.join(running)}\x60, not the unit's "
                    f"\x60{shown}\x60: it runs the code installed when it started"
                ),
                restart_hint,
            )
        ]
