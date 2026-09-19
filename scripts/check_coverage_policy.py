#!/usr/bin/env python3
"""Enforce per-module branch-coverage targets and temporary ratchet floors."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "quality-policy.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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
    )

    for line in debts:
        print(f"DEBT: {line}")
    for line in errors:
        print(f"ERROR: {line}", file=sys.stderr)
    print(
        f"coverage-policy: {len(source_modules(full_report))} production modules; "
        f"{len(debts)} below final target, {len(errors)} errors"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
