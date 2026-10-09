#!/usr/bin/env python3
"""Enforce per-module branch-coverage targets and temporary ratchet floors."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "quality-policy.json"
DEFAULT_SOURCE_ROOT = ROOT / "src" / "binnacle"
DEFAULT_SCRIPTS_ROOT = ROOT / "scripts"


def expected_source_modules(source_root: Path = DEFAULT_SOURCE_ROOT) -> set[str]:
    """The live Python inventory; coverage cannot quietly omit source files."""
    if not source_root.is_dir():
        return set()
    return {
        "src/binnacle/" + path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*.py")
        if path.name != "__init__.py" and path.is_file()
    }


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def expected_script_modules(scripts_root: Path = DEFAULT_SCRIPTS_ROOT) -> set[str]:
    """Repository scripts must all be present, even when unexecuted."""
    if not scripts_root.is_dir():
        return set()
    return {
        "scripts/" + path.name
        for path in scripts_root.glob("*.py")
        if path.name != "__init__.py" and path.is_file()
    }


def script_modules(report: dict[str, Any]) -> dict[str, float]:
    """Only top-level first-party scripts; not tests or vendored helpers."""
    return {
        path.replace("\\", "/"): float(
            item.get("summary", {}).get("percent_covered", 0.0)
        )
        for path, item in report.get("files", {}).items()
        if path.replace("\\", "/").startswith("scripts/")
        and path.replace("\\", "/").count("/") == 1
        and not path.endswith("/__init__.py")
    }


def evaluate_script_coverage(
    full_report: dict[str, Any],
    policy: dict[str, Any],
    *,
    expected_modules: set[str],
) -> tuple[list[str], list[str]]:
    """Fail closed on missing scripts; ratchet only reviewed critical ones."""
    cfg = policy.get("infrastructure_coverage")
    if not isinstance(cfg, dict):
        return ["missing infrastructure_coverage policy"], []
    floors = cfg.get("critical_minimums")
    if not isinstance(floors, dict) or not floors:
        return ["infrastructure_coverage critical_minimums are empty"], []
    measured = script_modules(full_report)
    errors: list[str] = []
    debts: list[str] = []
    if not expected_modules:
        errors.append("repository script inventory is empty or unreadable")
    for missing in sorted(expected_modules - measured.keys()):
        errors.append(f"{missing}: missing from script coverage report")
    for stale in sorted(measured.keys() - expected_modules):
        errors.append(f"{stale}: script coverage has no corresponding source file")
    target = float(cfg.get("eventual_target", 90.0))
    if not 0 < target <= 100:
        errors.append("infrastructure_coverage eventual_target must be in (0, 100]")
    for name, value in sorted(floors.items()):
        if name not in expected_modules:
            errors.append(f"{name}: critical coverage floor references absent source")
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(f"{name}: critical coverage floor is not numeric")
            continue
        floor = float(value)
        if not 0 <= floor <= 100:
            errors.append(f"{name}: critical coverage floor is outside 0..100")
            continue
        actual = measured.get(name)
        if actual is None:
            continue  # The missing-file check already fails.
        if not math.isfinite(actual) or not 0 <= actual <= 100:
            errors.append(f"{name}: invalid script coverage percentage")
            continue
        if actual + 1e-9 < floor:
            errors.append(
                f"{name}: script branch coverage {actual:.2f}% is below reviewed floor {floor:.2f}%"
            )
        if actual + 1e-9 < target:
            debts.append(
                f"{name}: script branch coverage {actual:.2f}% below eventual target {target:.2f}%"
            )
    return errors, debts


def source_modules(report: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for path, item in report.get("files", {}).items():
        normalized = path.replace("\\", "/")
        if not normalized.startswith("src/binnacle/"):
            continue
        if (
            normalized.endswith("/__init__.py")
            or normalized == "src/binnacle/__init__.py"
        ):
            continue
        summary = item.get("summary", {})
        out[normalized] = float(summary.get("percent_covered", 0.0))
    return out


def evaluate(
    unit_report: dict[str, Any],
    full_report: dict[str, Any],
    policy: dict[str, Any],
    *,
    strict: bool = False,
    expected_modules: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    cfg = policy["coverage"]
    core_target = float(cfg["core_unit_target"])
    other_target = float(cfg["other_full_target"])
    core = set(cfg["core_modules"])
    floors = cfg.get("temporary_floors", {})
    unit_floors = {str(k): float(v) for k, v in floors.get("unit", {}).items()}
    full_floors = {str(k): float(v) for k, v in floors.get("full", {}).items()}

    unit = source_modules(unit_report)
    full = source_modules(full_report)
    errors: list[str] = []
    debts: list[str] = []

    if not full:
        return ["full coverage report contains no src/binnacle modules"], []

    if expected_modules is not None:
        if not expected_modules:
            errors.append("production Python inventory is empty or unreadable")
        for missing in sorted(expected_modules - full.keys()):
            errors.append(f"{missing}: missing from full coverage report")
        for stale in sorted(full.keys() - expected_modules):
            errors.append(f"{stale}: coverage report has no corresponding source file")

    for module in sorted(full):
        if module in core:
            scope = "unit"
            actual = unit.get(module)
            target = core_target
            floor = unit_floors.get(module)
        else:
            scope = "full"
            actual = full.get(module)
            target = other_target
            floor = full_floors.get(module)

        if actual is None:
            errors.append(f"{module}: missing from {scope} coverage report")
            continue
        if not math.isfinite(actual) or not 0 <= actual <= 100:
            errors.append(f"{module}: invalid {scope} coverage percentage")
            continue

        required = target if strict or floor is None else floor
        if actual + 1e-9 < required:
            errors.append(
                f"{module}: {scope} branch coverage {actual:.2f}% "
                f"is below required {required:.2f}% (target {target:.2f}%)"
            )
            continue

        if actual + 1e-9 < target:
            debts.append(
                f"{module}: {scope} branch coverage {actual:.2f}% "
                f"below final target {target:.2f}%"
            )
        elif not strict and floor is not None and floor < target:
            errors.append(
                f"{module}: coverage reached {actual:.2f}% target; "
                f"remove obsolete temporary {scope} floor {floor:.2f}%"
            )

    for module in sorted(core):
        if module not in full:
            errors.append(f"{module}: core module missing from full coverage report")

    for module in sorted(unit_floors):
        if module not in core:
            errors.append(
                f"{module}: unit floor exists but module is not classified core"
            )
    for module in sorted(full_floors):
        if module in core:
            errors.append(
                f"{module}: full floor exists for core module; use unit floor"
            )

    return errors, debts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--unit-json", type=Path, required=True)
    parser.add_argument("--full-json", type=Path, required=True)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Ignore temporary floors and require the final 95/90 targets.",
    )
    args = parser.parse_args(argv)

    policy = load_json(args.policy)
    unit_report = load_json(args.unit_json)
    full_report = load_json(args.full_json)
    errors, debts = evaluate(
        unit_report,
        full_report,
        policy,
        strict=args.strict,
        expected_modules=expected_source_modules(),
    )
    script_errors, script_debts = evaluate_script_coverage(
        full_report, policy, expected_modules=expected_script_modules()
    )
    errors.extend(script_errors)
    debts.extend(script_debts)

    for line in debts:
        print(f"DEBT: {line}")
    for line in errors:
        print(f"ERROR: {line}", file=sys.stderr)
    print(
        f"coverage-policy: {len(source_modules(full_report))} production modules, "
        f"{len(script_modules(full_report))} script modules; "
        f"{len(debts)} below final target, {len(errors)} errors"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
