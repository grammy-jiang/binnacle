#!/usr/bin/env python3
"""Enforce the repository's Python module-size ratchet."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "quality-policy.json"


def load_policy(path: Path = DEFAULT_POLICY) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def tracked_python_files(root: Path, roots: tuple[str, ...]) -> list[Path]:
    proc = subprocess.run(
        [
            "git",
            "ls-files",
            "-co",
            "--exclude-standard",
            "--",
            "*.py",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    allowed = tuple(f"{name.rstrip('/')}/" for name in roots)
    out: list[Path] = []
    for raw in proc.stdout.splitlines():
        path = root / raw
        if raw.startswith(allowed) and path.is_file():
            out.append(path)
    return sorted(set(out))


def physical_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def evaluate(
    measurements: dict[str, int],
    policy: dict[str, Any],
    *,
    strict: bool = False,
) -> tuple[list[str], list[str], list[str]]:
    cfg = policy["module_size"]
    warning_lines = int(cfg["warning_lines"])
    max_lines = int(cfg["max_lines"])
    legacy = {str(k): int(v) for k, v in cfg.get("legacy_oversize", {}).items()}

    errors: list[str] = []
    debts: list[str] = []
    warnings: list[str] = []

    for path, lines in sorted(measurements.items()):
        if lines > max_lines:
            baseline = legacy.get(path)
            if strict:
                errors.append(f"{path}: {lines} lines exceeds hard limit {max_lines}")
            elif baseline is None:
                errors.append(
                    f"{path}: {lines} lines exceeds {max_lines} and has no legacy baseline"
                )
            elif lines > baseline:
                errors.append(
                    f"{path}: {lines} lines grew beyond legacy baseline {baseline}"
                )
            else:
                debts.append(
                    f"{path}: {lines} lines remains above target {max_lines} "
                    f"(legacy ceiling {baseline})"
                )
        elif lines > warning_lines:
            warnings.append(
                f"{path}: {lines} lines is above warning threshold {warning_lines}"
            )

    if not strict:
        for path, baseline in sorted(legacy.items()):
            current = measurements.get(path)
            if current is None:
                errors.append(
                    f"{path}: stale legacy baseline {baseline}; file is missing, remove it"
                )
            elif current <= max_lines:
                errors.append(
                    f"{path}: now {current} lines; remove the obsolete legacy baseline"
                )

    return errors, debts, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on every module above the final 500-line target.",
    )
    args = parser.parse_args(argv)

    policy = load_policy(args.policy)
    roots = tuple(policy["module_size"]["roots"])
    files = tracked_python_files(ROOT, roots)
    measurements = {str(path.relative_to(ROOT)): physical_lines(path) for path in files}
    errors, debts, warnings = evaluate(measurements, policy, strict=args.strict)

    for line in warnings:
        print(f"WARNING: {line}")
    for line in debts:
        print(f"DEBT: {line}")
    for line in errors:
        print(f"ERROR: {line}", file=sys.stderr)

    print(
        f"module-size: {len(measurements)} Python modules checked; "
        f"{len(debts)} legacy oversized, {len(warnings)} warnings, {len(errors)} errors"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
