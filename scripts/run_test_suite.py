"""Run the managed test suite in parallel-safe and ordinary-process lanes."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence

WORKER_ENV = "BINNACLE_TEST_WORKERS"
MAX_DEFAULT_WORKERS = 4


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer >= 1") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be an integer >= 1")
    return parsed


def resolve_workers(
    cli_workers: int | None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Resolve workers using CLI, environment, then the bounded CPU default."""
    if cli_workers is not None:
        if cli_workers < 1:
            raise ValueError("workers must be >= 1")
        return cli_workers

    env = os.environ if environ is None else environ
    raw = env.get(WORKER_ENV)
    if raw is not None:
        try:
            return _positive_int(raw)
        except argparse.ArgumentTypeError as exc:
            raise ValueError(f"{WORKER_ENV} {exc}") from exc

    return min(MAX_DEFAULT_WORKERS, os.cpu_count() or 1)


def build_lane_commands(
    *,
    workers: int,
    seed: int | None,
    shared_args: Sequence[str],
) -> tuple[list[str], list[str]]:
    """Build the parallel-safe and ordinary-process pytest commands."""
    common = [sys.executable, "-m", "pytest", "tests", "-q"]
    main = [*common, "-m", "not no_xdist"]
    ordinary = [*common, "-m", "no_xdist"]

    if workers > 1:
        main.extend(["-n", str(workers), "--dist=worksteal"])

    if seed is not None:
        seed_arg = f"--randomly-seed={seed}"
        main.append(seed_arg)
        ordinary.append(seed_arg)

    main.extend(shared_args)
    ordinary.extend(shared_args)
    return main, ordinary


def _run_lane(name: str, command: Sequence[str]) -> tuple[int, float]:
    print(f"{name} command: {shlex.join(command)}", flush=True)
    started = time.perf_counter()
    proc = subprocess.run(list(command), check=False)
    elapsed = time.perf_counter() - started
    print(f"{name} exit code: {proc.returncode}", flush=True)
    print(f"{name} elapsed: {elapsed:.2f}s", flush=True)
    return proc.returncode, elapsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the full managed test suite in its two required lanes."
    )
    parser.add_argument("--workers", type=_positive_int)
    parser.add_argument("--seed", type=int)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    parser = _parser()
    args, shared_args = parser.parse_known_args(argv)

    try:
        workers = resolve_workers(args.workers, environ)
    except ValueError as exc:
        parser.error(str(exc))

    main_command, ordinary_command = build_lane_commands(
        workers=workers,
        seed=args.seed,
        shared_args=shared_args,
    )

    total_started = time.perf_counter()
    main_code, _ = _run_lane("parallel-safe lane", main_command)
    ordinary_code, _ = _run_lane("ordinary-process lane", ordinary_command)
    total_elapsed = time.perf_counter() - total_started

    print(f"total elapsed: {total_elapsed:.2f}s", flush=True)
    print(f"resolved workers: {workers}", flush=True)
    return 1 if main_code or ordinary_code else 0


if __name__ == "__main__":
    raise SystemExit(main())
