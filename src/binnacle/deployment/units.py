"""Managed systemd user units: render, mark, compare, adopt, verify.

Every unit Binnacle writes starts with a marker line that names the command
managing it and the parameters it was rendered from::

    # Managed by binnacle (binnacle-watchdog setup): watchdog=/x/bin/binnacle-watchdog

`setup` tells its own files from hand-written ones by that line and refuses
to overwrite a stranger's unless told to adopt it, showing the diff either
way. A doctor re-renders the unit from the recorded parameters and reports
any difference, and checks that the running process is what the unit
starts. The 2026-09-20 incident is why: a CLI split moved the watchdog to a
new command while the unit on disk kept starting the old one, and nothing
noticed until a restart would have looped.

This module is client-neutral. It knows nothing about the server, the
tunnel or the watchdog; each owner supplies its template and parameters.
"""

import difflib
import re
import shlex
import shutil
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from binnacle.doctor_contracts import Check, fail, ok, warn

Systemctl = Callable[..., object]

UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
MARKER_PREFIX = "# Managed by binnacle"
#: What every `setup` wrote until 2026-09-20: ours, but without parameters.
LEGACY_MARKER = "# Managed by `binnacle setup`"
_MARKER_RE = re.compile(r"^# Managed by binnacle \(([\w.-]+) setup\)(?::\s*(.*))?$")


class UnitError(Exception):
    """A unit cannot be rendered or written; the message says why."""


@dataclass(frozen=True, slots=True)
class UnitSpec:
    """A unit as its owner renders it: name, owning command, body, and the
    parameters the body came from (recorded in the marker line)."""

    name: str
    owner: str
    body: str
    params: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Marker:
    """The provenance a unit file declares on its first line."""

    owner: str
    params: dict[str, str]
    legacy: bool = False


def marker_line(owner: str, params: Mapping[str, str]) -> str:
    rendered = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in params.items())
    return f"{MARKER_PREFIX} ({owner} setup)" + (f": {rendered}" if rendered else "")


def read_marker(text: str) -> Marker | None:
    """The marker of a unit file; None for a file no setup command wrote."""
    first = text.split("\n", 1)[0].strip() if text else ""
    if first == LEGACY_MARKER:
        return Marker("", {}, legacy=True)
    m = _MARKER_RE.match(first)
    if m is None:
        return None
    params: dict[str, str] = {}
    for token in shlex.split(m.group(2) or ""):
        key, _, value = token.partition("=")
        params[key] = value
    return Marker(m.group(1), params)


def render(spec: UnitSpec) -> str:
    return marker_line(spec.owner, spec.params) + "\n" + spec.body


def unit_diff(current: str | None, new: str, name: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            (current or "").splitlines(),
            new.splitlines(),
            f"{name} (on disk)",
            f"{name} (setup would write)",
            lineterm="",
            n=1,
        )
    )


@dataclass(frozen=True, slots=True)
class WritePlan:
    """What `setup` would do to a unit file: create, rewrite, unchanged or
    refuse, with the text it would write, the diff, and the reason."""

    action: str
    text: str
    diff: str = ""
    reason: str = ""


def plan_write(path: Path, spec: UnitSpec, adopt: bool = False) -> WritePlan:
    """Decide what writing `spec` to `path` means. A file no setup command
    wrote, or one another command manages, is refused unless `adopt`."""
    new = render(spec)
    if not path.exists():
        return WritePlan("create", new)
    current = path.read_text(encoding="utf-8")
    if current == new:
        return WritePlan("unchanged", new)
    diff = unit_diff(current, new, spec.name)
    marker = read_marker(current)
    if marker is None:
        if adopt:
            return WritePlan("rewrite", new, diff)
        return WritePlan(
            "refuse",
            new,
            diff,
            f"refusing to overwrite {path}: no binnacle setup command wrote it "
            "(no marker line). Review the diff, then pass --adopt to take it "
            "over, or move it away.",
        )
    if not marker.legacy and marker.owner != spec.owner and not adopt:
        return WritePlan(
            "refuse",
            new,
            diff,
            f"refusing to overwrite {path}: `{marker.owner} setup` manages "
            f"it, not `{spec.owner} setup`. Pass --adopt to take it over.",
        )
    return WritePlan("rewrite", new, diff)


def write_unit(
    path: Path, plan: WritePlan, backup_dir: Path | None = None
) -> Path | None:
    """Write the planned text. An existing file is copied to `backup_dir`
    first, as <unit>.<timestamp>; the copy's path is returned."""
    backup: Path | None = None
    if path.exists() and backup_dir is not None:
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"{path.name}.{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.text, encoding="utf-8")
    return backup


def _linux_unit_inspection():
    """Only this explicitly Linux-compatible legacy API selects unit mechanics."""
    from binnacle.deployment.linux.unit_inspection import LinuxUnitInspection

    return LinuxUnitInspection()


def resolve_executable(
    name: str,
    argv0: str | None = None,
    which: Callable[[str], str | None] | None = None,
) -> Path:
    """Compatibility facade for Linux's verified systemd ExecStart path."""
    try:
        return _linux_unit_inspection().resolve_executable(
            name, argv0 or sys.argv[0], which
        )
    except ValueError as exc:
        raise UnitError(str(exc)) from None


def exec_start_argv(value: str) -> list[str]:
    """Compatibility facade for systemctl's exact ExecStart serialization."""
    return _linux_unit_inspection().exec_start_argv(value)


def proc_cmdline(pid: int) -> list[str]:
    """Compatibility facade for Linux procfs process command lines."""
    return _linux_unit_inspection().proc_cmdline(pid)


def unit_property(unit: str, prop: str, run: Systemctl | None = None) -> str:
    """Compatibility facade for Linux managed-unit inspection."""
    return _linux_unit_inspection().unit_property(unit, prop, run)


def unit_waits_for_ready(unit: str, run: Systemctl | None = None) -> bool:
    return bool(unit_property(unit, "ExecStartPost", run))


def check_unit_process(
    unit: str,
    group: str,
    setup_hint: str,
    restart_hint: str,
    run: Systemctl | None = None,
    cmdline: Callable[[int], list[str]] = proc_cmdline,
) -> list[Check]:
    """Convert Linux process facts to the existing generic diagnostics contract."""
    facts = _linux_unit_inspection().inspect_process(
        unit,
        group,
        setup_hint,
        restart_hint,
        property_reader=lambda service, property_name: unit_property(
            service, property_name, run
        ),
        cmdline=cmdline,
        parse_exec=exec_start_argv,
    )
    out: list[Check] = []
    for level, category, description, hint in facts:
        if level == "ok":
            out.append(ok(category, description))
        elif level == "warn":
            out.append(warn(category, description, hint or ""))
        else:
            out.append(fail(category, description, hint or ""))
    return out


def check_unit_drift(
    path: Path,
    owner: str,
    render_for: Callable[[Mapping[str, str]], str],
    group: str,
    setup_hint: str,
) -> list[Check]:
    """Is the unit file what its owner's `setup` writes today? The marker
    line supplies the parameters; `render_for` renders them again."""
    if not path.exists():
        return [fail(group, f"{path} does not exist", setup_hint)]
    text = path.read_text(encoding="utf-8")
    marker = read_marker(text)
    if marker is None:
        return [
            warn(
                group,
                f"{path.name} was not written by `{owner} setup` (no marker "
                "line); its content is not verified",
                f"review `{setup_hint} --dry-run`, then `{setup_hint} --adopt`",
            )
        ]
    if marker.legacy:
        return [
            warn(
                group,
                f"{path.name} carries the pre-2026-09-20 marker without "
                "parameters; its content is not verified",
                setup_hint,
            )
        ]
    if marker.owner != owner:
        return [
            warn(
                group,
                f"{path.name} is managed by `{marker.owner} setup`, "
                f"not `{owner} setup`",
                setup_hint,
            )
        ]
    try:
        expected = render_for(marker.params)
    except (UnitError, KeyError) as e:
        return [
            warn(
                group,
                f"{path.name}: its marker parameters cannot be rendered by this "
                f"version ({e})",
                setup_hint,
            )
        ]
    if expected != text:
        first = next(
            (
                line
                for line in unit_diff(text, expected, path.name).splitlines()[2:]
                if line[:1] in "+-"
            ),
            "",
        )
        return [
            warn(
                group,
                f"{path.name} differs from what `{owner} setup` writes now "
                f"(first difference: {first.strip()})",
                f"{setup_hint}, then restart the unit at a quiet moment",
            )
        ]
    shown = ", ".join(f"{k}={v}" for k, v in marker.params.items()) or "no parameters"
    return [ok(group, f"{path.name} matches `{owner} setup` ({shown})")]
