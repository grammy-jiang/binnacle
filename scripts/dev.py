#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Repository development bootstrap, doctor, and worktree inventory.

Run this through uv so it remains usable before the project virtual environment
exists:

    uv run scripts/dev.py bootstrap
    uv run scripts/dev.py doctor
    uv run scripts/dev.py worktrees

The script intentionally uses only the standard library. The PEP 723 metadata
makes the uv-run entry point independent of the project's .venv, which is
important because creating and validating that environment is part of the
bootstrap job itself.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.dev_common import CommandResult, Runner, Which
from scripts.dev_worktrees import WorktreeStatus, worktree_inventory

ROOT = Path(__file__).resolve().parents[1]
HOOK_TYPES_RE = re.compile(r"(?m)^default_install_hook_types\s*:\s*\[([^\]]*)\]\s*$")


@dataclasses.dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def _run(argv: Sequence[str], cwd: Path) -> CommandResult:
    try:
        environ = dict(os.environ)
        # uv gives PEP 723 scripts their own temporary VIRTUAL_ENV. Child
        # repository commands must target this checkout's .venv instead.
        environ.pop("VIRTUAL_ENV", None)
        proc = subprocess.run(
            list(argv),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            env=environ,
        )
    except OSError as exc:
        return CommandResult(127, str(exc))
    return CommandResult(proc.returncode, (proc.stdout or "") + (proc.stderr or ""))


def locked_uv_version(root: Path = ROOT) -> str | None:
    """Return the exact uv tool version carried by the repository lock."""

    for block in (root / "uv.lock").read_text(encoding="utf-8").split("[[package]]"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() in {"name", "version"}:
                fields[key.strip()] = value.strip().strip(chr(34))
        if fields.get("name") == "uv":
            return fields.get("version")
    return None


def configured_hook_types(root: Path = ROOT) -> tuple[str, ...]:
    """Return pre-commit's configured install hook types."""

    text = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    match = HOOK_TYPES_RE.search(text)
    if not match:
        return ("pre-commit",)
    values = []
    for item in match.group(1).split(","):
        value = item.strip().strip("'\"")
        if value:
            values.append(value)
    return tuple(values) or ("pre-commit",)


def bootstrap_commands(uv: str) -> tuple[tuple[str, ...], ...]:
    return (
        (uv, "sync", "--locked", "--group", "dev"),
        (uv, "run", "--no-sync", "pre-commit", "install"),
    )


def _uv_version(uv: str, root: Path, run: Runner) -> str | None:
    result = run((uv, "--version"), root)
    if result.returncode:
        return None
    parts = result.output.strip().split()
    return parts[1] if len(parts) >= 2 and parts[0] == "uv" else None


def _hook_path(git: str, hook: str, root: Path, run: Runner) -> Path | None:
    result = run((git, "rev-parse", "--git-path", f"hooks/{hook}"), root)
    if result.returncode or not result.output.strip():
        return None
    path = Path(result.output.strip().splitlines()[-1])
    return path if path.is_absolute() else root / path


def doctor(
    root: Path = ROOT,
    *,
    run: Runner = _run,
    which: Which = shutil.which,
) -> list[Check]:
    """Check the current checkout without changing it."""

    root = root.resolve()
    checks: list[Check] = []

    git = which("git")
    if git is None:
        checks.append(Check("git", "fail", "git is not on PATH"))
    else:
        top = run((git, "rev-parse", "--show-toplevel"), root)
        if top.returncode:
            checks.append(
                Check("git", "fail", top.output.strip() or "not a Git checkout")
            )
        elif Path(top.output.strip()).resolve() != root:
            checks.append(
                Check(
                    "git",
                    "fail",
                    f"checkout root is {top.output.strip()}, expected {root}",
                )
            )
        else:
            checks.append(Check("git", "ok", str(root)))

        status = run((git, "status", "--porcelain"), root)
        if status.returncode:
            checks.append(Check("working-tree", "fail", status.output.strip()))
        else:
            changes = [line for line in status.output.splitlines() if line.strip()]
            if changes:
                checks.append(
                    Check(
                        "working-tree",
                        "warn",
                        f"{len(changes)} tracked/untracked change(s); doctor is still read-only",
                    )
                )
            else:
                checks.append(Check("working-tree", "ok", "clean"))

    uv = which("uv")
    required = locked_uv_version(root)
    if uv is None:
        checks.append(Check("uv", "fail", "uv is not on PATH"))
    else:
        actual = _uv_version(uv, root, run)
        if required is None:
            checks.append(
                Check(
                    "uv", "fail", "cannot read the locked uv tool version from uv.lock"
                )
            )
        elif actual != required:
            checks.append(
                Check("uv", "fail", f"{actual or '?'} installed; {required} required")
            )
        else:
            checks.append(Check("uv", "ok", actual))

        lock = run((uv, "lock", "--check", "--offline"), root)
        checks.append(
            Check(
                "uv.lock",
                "ok" if lock.returncode == 0 else "fail",
                "current"
                if lock.returncode == 0
                else (lock.output.strip() or "lock drift"),
            )
        )

    rg = which("rg")
    if rg is None:
        checks.append(Check("ripgrep", "fail", "rg is not on PATH"))
    else:
        version = run((rg, "--version"), root)
        detail = version.output.splitlines()[0] if version.output else rg
        checks.append(
            Check("ripgrep", "ok" if version.returncode == 0 else "fail", detail)
        )

    venv_python = root / ".venv" / "bin" / "python"
    expected_python = (
        (root / ".python-version").read_text(encoding="utf-8").strip()
        if (root / ".python-version").exists()
        else ""
    )
    if not venv_python.exists():
        checks.append(Check("venv", "fail", ".venv/bin/python is missing"))
    else:
        version = run(
            (
                str(venv_python),
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
            ),
            root,
        )
        actual_python = (
            version.output.strip().splitlines()[-1] if version.output.strip() else "?"
        )
        if version.returncode:
            checks.append(
                Check("venv", "fail", version.output.strip() or "Python failed")
            )
        elif expected_python and actual_python != expected_python:
            checks.append(
                Check(
                    "venv",
                    "fail",
                    f"Python {actual_python}; .python-version requires {expected_python}",
                )
            )
        else:
            checks.append(Check("venv", "ok", f"Python {actual_python}"))

    if git is not None:
        for hook in configured_hook_types(root):
            path = _hook_path(git, hook, root, run)
            if path is None:
                checks.append(
                    Check(f"hook:{hook}", "fail", "Git hook path unavailable")
                )
            elif not path.exists():
                checks.append(Check(f"hook:{hook}", "fail", f"missing: {path}"))
            elif not os.access(path, os.X_OK):
                checks.append(Check(f"hook:{hook}", "fail", f"not executable: {path}"))
            else:
                checks.append(Check(f"hook:{hook}", "ok", str(path)))

    return checks


def _print_checks(checks: Sequence[Check], *, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                [dataclasses.asdict(check) for check in checks],
                indent=2,
            )
        )
        return
    for check in checks:
        print(f"[{check.status.upper():4}] {check.name}: {check.detail}")
    failures = sum(check.status == "fail" for check in checks)
    warnings = sum(check.status == "warn" for check in checks)
    print(
        f"Summary: {len(checks) - failures - warnings} ok, "
        f"{warnings} warning(s), {failures} failure(s)"
    )


def _print_worktrees(
    items: Sequence[WorktreeStatus],
    *,
    as_json: bool,
) -> None:
    if as_json:
        print(
            json.dumps(
                [dataclasses.asdict(item) for item in items],
                indent=2,
            )
        )
        return
    print(f"Worktrees: {len(items)}")
    for item in items:
        print(f"[{','.join(item.flags)}] {item.path}")
        relation = ""
        if item.ahead is not None and item.behind is not None:
            relation = f" (ahead {item.ahead}, behind {item.behind})"
        dirty = "unknown" if item.dirty_changes is None else str(item.dirty_changes)
        merged = (
            "unknown"
            if item.merged_to_master is None
            else "yes"
            if item.merged_to_master
            else "no"
        )
        print(f"  branch={item.branch} head={item.head}")
        print(f"  upstream={item.upstream}{relation} merged-to-master={merged}")
        print(
            f"  dirty-changes={dirty} "
            f"venv={'yes' if item.venv else 'no'} lock={item.lock}"
        )
        if item.locked:
            print(f"  locked={item.locked}")


def bootstrap(
    root: Path = ROOT,
    *,
    run: Runner = _run,
    which: Which = shutil.which,
) -> int:
    root = root.resolve()
    uv = which("uv")
    if uv is None:
        print("ERROR: uv is not on PATH", file=sys.stderr)
        return 1

    required = locked_uv_version(root)
    actual = _uv_version(uv, root, run)
    if required is None or actual != required:
        print(
            f"ERROR: uv {actual or '?'} is installed; "
            f"repository lock requires {required or '?'}. "
            f"Update uv with: uv self update {required}",
            file=sys.stderr,
        )
        return 1

    for command in bootstrap_commands(uv):
        print(f"+ {' '.join(command)}", flush=True)
        result = run(command, root)
        if result.output:
            print(result.output.rstrip())
        if result.returncode:
            print(
                f"ERROR: command failed with exit {result.returncode}",
                file=sys.stderr,
            )
            return result.returncode

    checks = doctor(root, run=run, which=which)
    _print_checks(checks, as_json=False)
    return 1 if any(check.status == "fail" for check in checks) else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Binnacle repository development tooling."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "bootstrap",
        help="sync the dev environment, install hooks, and verify it",
    )

    doctor_parser = sub.add_parser(
        "doctor",
        help="read-only current-checkout validation",
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON",
    )

    worktrees_parser = sub.add_parser(
        "worktrees",
        help="read-only health inventory for all Git worktrees",
    )
    worktrees_parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "bootstrap":
        return bootstrap()
    if args.command == "doctor":
        checks = doctor()
        _print_checks(checks, as_json=args.json)
        return 1 if any(check.status == "fail" for check in checks) else 0
    if args.command == "worktrees":
        try:
            items = worktree_inventory(ROOT, run=_run, which=shutil.which)
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        _print_worktrees(items, as_json=args.json)
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
