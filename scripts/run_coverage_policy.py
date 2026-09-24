"""Generate unit-only and full-suite reports without re-running unit tests."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_test_suite as suite_runner


def build_pipeline_commands(
    *,
    workers: int,
    seed: int | None,
    unit_json: Path,
    full_json: Path,
    shared_args: Sequence[str],
) -> list[tuple[str, list[str]]]:
    """Build the ordered coverage-data pipeline."""
    coverage_base = [
        "--cov=binnacle",
        "--cov-branch",
        "--cov-fail-under=0",
        "--cov-report=",
    ]
    coverage_append = [*coverage_base, "--cov-append"]

    unit_main = suite_runner.build_pytest_lane_command(
        test_args=["tests/unit"],
        workers=workers,
        seed=seed,
        shared_args=[*coverage_base, *shared_args],
        no_xdist=False,
    )
    unit_ordinary = suite_runner.build_pytest_lane_command(
        test_args=["tests/unit"],
        workers=workers,
        seed=seed,
        shared_args=[*coverage_append, *shared_args],
        no_xdist=True,
    )
    nonunit_main = suite_runner.build_pytest_lane_command(
        test_args=["tests", "--ignore=tests/unit"],
        workers=workers,
        seed=seed,
        shared_args=[*coverage_append, *shared_args],
        no_xdist=False,
    )
    nonunit_ordinary = suite_runner.build_pytest_lane_command(
        test_args=["tests", "--ignore=tests/unit"],
        workers=workers,
        seed=seed,
        shared_args=[*coverage_append, *shared_args],
        no_xdist=True,
    )

    return [
        ("coverage erase", [sys.executable, "-m", "coverage", "erase"]),
        ("unit parallel-safe lane", unit_main),
        ("unit ordinary-process lane", unit_ordinary),
        (
            "unit coverage json",
            [
                sys.executable,
                "-m",
                "coverage",
                "json",
                "--fail-under=0",
                "-o",
                str(unit_json),
            ],
        ),
        ("non-unit parallel-safe lane", nonunit_main),
        ("non-unit ordinary-process lane", nonunit_ordinary),
        (
            "full coverage json",
            [
                sys.executable,
                "-m",
                "coverage",
                "json",
                "--fail-under=0",
                "-o",
                str(full_json),
            ],
        ),
    ]


def _run_step(name: str, command: Sequence[str]) -> int:
    print(f"{name} command: {shlex.join(command)}", flush=True)
    proc = subprocess.run(list(command), check=False)
    print(f"{name} exit code: {proc.returncode}", flush=True)
    return proc.returncode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate unit-only and full managed-suite branch-coverage reports "
            "without executing unit tests twice."
        )
    )
    parser.add_argument("--workers", type=suite_runner._positive_int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--unit-json", type=Path, required=True)
    parser.add_argument("--full-json", type=Path, required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    parser = _parser()
    args, shared_args = parser.parse_known_args(argv)

    try:
        workers = suite_runner.resolve_workers(args.workers, environ)
    except ValueError as exc:
        parser.error(str(exc))

    commands = build_pipeline_commands(
        workers=workers,
        seed=args.seed,
        unit_json=args.unit_json,
        full_json=args.full_json,
        shared_args=shared_args,
    )

    print(f"resolved workers: {workers}", flush=True)
    for name, command in commands:
        code = _run_step(name, command)
        if code:
            print(
                f"coverage pipeline stopped after {name} with exit code {code}",
                flush=True,
            )
            return code

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
