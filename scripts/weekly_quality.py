#!/usr/bin/env python3
"""The weekly quality run (docs/quality-guard-plan-2026-09-27.md, step 3).

    scripts/weekly_quality.py [--quiet-ok] [--seeds N] [--mutation-modules N]
                              [--only usage,bench,flake,mutation]
                              [--budget-min M] [--rebaseline]

It never runs in the production checkout and never calls the production
server. First it updates its own clone (~/.local/state/binnacle/
quality-weekly/checkout) to origin/master with a frozen venv, and runs that
clone's copy of this script (``--prepared``). Then, each job in its own
1-CPU user scope and only at a quiet moment (scripts/weekly_scope.py):

1. usage: the week's production numbers, read-only from the journal
   (scripts/weekly_usage.py);
2. bench: a fixed benchmark against a temporary server on a free port
   (scripts/weekly_bench.py);
3. flake: the full suite once per seed under load inside its scope
   (scripts/weekly_flake.py);
4. mutation: two core modules in rotation (scripts/weekly_mutation.py).

Output follows cron-report: the first line is ``OK: ...``, ``WARN: ...`` or
``ALERT: ...``; ``--quiet-ok`` prints nothing when every check passed. A job
that found no quiet moment, no time in the budget, or was stopped for
production calls twice is a WARN: a week without the check must not look
like a clean week. The
exit code is non-zero only when the run itself broke. Every run keeps its
report, junit files and logs in the state directory (the newest eight).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shlex
import shutil
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

if __package__ in (None, ""):  # run as a script: make `scripts` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.smoke_checks import Report, last_line
from scripts.weekly_bench import REPS
from scripts.weekly_bench_checks import bench_checks
from scripts.weekly_flake import DEFAULT_SEEDS, flake_hunt, seeds_for
from scripts.weekly_host import (
    REMOTE_URL,
    STATE_DIR,
    Host,
    default_host,
    job_env,
    user_bus_env,
    uv_binary,
)
from scripts.weekly_mutation import PER_WEEK, mutation_rotation
from scripts.weekly_scope import Limits, Runner, probe_scope, scope_argv, unit_name
from scripts.weekly_usage import journal_latency, usage_checks

JOBS = ("usage", "bench", "flake", "mutation")
BUDGET_S = 3 * 3600
FLAKE_SHARE = 0.5  # the flake hunt may use at most half of what is left
KEEP_RUNS = 8
WEEK_S = 7 * 86400


def prepare_script(clone: Path, remote: str, ref: str = "origin/master") -> str:
    """Shell steps that bring the clone to ``ref`` with a frozen venv."""
    q = shlex.quote
    steps = (
        []
        if (clone / ".git").exists()
        else [f"git clone -q {q(remote)} {q(str(clone))}"]
    )
    steps += [
        f"cd {q(str(clone))}",
        "git fetch -q origin",
        f"git checkout -q --force --detach {q(ref)}",
        "git clean -qfdx -e .venv",
        f"{q(uv_binary())} sync -q --frozen",
        "git rev-parse --short HEAD",
    ]
    return " && ".join(["set -e", *steps])


def prepare(host: Host, stamp: str, clone: Path, ref: str) -> tuple[str, str]:
    """(commit, problem): update the clone inside a limited scope."""
    clone.parent.mkdir(parents=True, exist_ok=True)
    script = prepare_script(clone, REMOTE_URL, ref)
    argv = scope_argv(unit_name(stamp, "prepare"), 900, ["/bin/sh", "-c", script])
    rc, out = host.run(argv, 960)
    if rc != 0:
        return "", f"could not update the clone (exit {rc}): {last_line(out)}"
    return last_line(out), ""


def _stamp(epoch: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))


def impact_lines(host: Host, runner: Runner, started: float) -> list[str]:
    """What the run cost production: load and memory while jobs ran, and the
    production calls of the run's window against the hour before it."""
    ended = host.now()
    during, _ = journal_latency(host.journal(started, ended))
    before, _ = journal_latency(host.journal(started - 3600, started))

    def calls(table: dict) -> str:
        if not table:
            return "no production calls"
        return ", ".join(
            f"{t} {r['n']}x p50 {r['p50_ms']:.0f} ms" for t, r in table.items()
        )

    return [
        f"Jobs: {runner.samples.summary()}",
        f"Production during the run ({_stamp(started)} .. {_stamp(ended)}): {calls(during)}",
        f"Production in the hour before: {calls(before)}",
    ]


def run_jobs(
    args: argparse.Namespace, host: Host, runner: Runner, clone: Path
) -> Report:
    report = Report()
    only = set(args.only.split(",")) if args.only else set(JOBS)
    if "usage" in only:
        now = host.now()
        report.checks += usage_checks(
            runner, clone, args.state_dir, _stamp(now - WEEK_S), _stamp(now)
        )
    if "bench" in only:
        report.checks += bench_checks(
            runner, clone, args.state_dir, args.reps, args.rebaseline
        )
    if "flake" in only:
        share = FLAKE_SHARE if "mutation" in only else 1.0
        cap = host.now() + (runner.deadline - host.now()) * share
        flake_runner = dataclasses.replace(runner, deadline=min(runner.deadline, cap))
        report.checks += flake_hunt(
            flake_runner, clone, seeds_for(runner.run_id, args.seeds)
        )
    if "mutation" in only:
        report.checks += mutation_rotation(
            runner, clone, args.state_dir, args.mutation_modules
        )
    return report


def headline(report: Report) -> str:
    bad = report.failing()
    if not bad:
        return f"{report.level.upper()}: weekly quality run passed ({len(report.checks)} checks)"
    text = "; ".join(f"{c.name}: {c.detail}" for c in bad)
    return f"{report.level.upper()}: {text[:200]}"


def prune(runs_dir: Path, keep: int) -> None:
    runs = sorted(p for p in runs_dir.iterdir() if p.is_dir())
    for old in runs[:-keep]:
        shutil.rmtree(old, ignore_errors=True)


def run(
    args: argparse.Namespace, host: Host, environ: dict[str, str]
) -> tuple[str, str]:
    """(level, report text) of one run in the clone."""
    started = host.now()
    run_id = time.strftime("%Y%m%dT%H%M%S", time.localtime(started))
    run_dir = args.state_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    report = Report()
    problem = probe_scope(host, run_id, run_dir / "probe.log")
    if problem:
        report.add("isolation", "alert", f"{problem}; nothing ran")
        return "alert", "\n".join([headline(report), *report.lines()])
    report.add(
        "isolation",
        "ok",
        "1-CPU idle-weight user scopes in force (cpu.max 100000 100000, cpu.idle 1); "
        "MemoryMax is not enforced here (no memory controller), the runner caps "
        "each scope at 2 GiB RSS",
    )
    commit = environ.get("BINNACLE_WEEKLY_COMMIT", "?")
    report.add("checkout", "ok", f"{args.clone} at {commit} ({args.ref})")
    runner = Runner(
        host=host,
        limits=Limits(load_max=args.load_max),
        run_id=run_id,
        run_dir=run_dir,
        env=job_env(environ, args.state_dir),
        deadline=started + args.budget_min * 60,
    )
    report.checks += run_jobs(args, host, runner, args.clone).checks
    lines = [headline(report), *report.lines(), "", "Timeline:"]
    lines += [f"  {t}" for t in runner.timeline] or ["  (no job ran)"]
    lines += ["", "Impact:", *(f"  {t}" for t in impact_lines(host, runner, started))]
    lines += ["", f"History: {run_dir / 'report.txt'}"]
    text = "\n".join(lines)
    (run_dir / "report.txt").write_text(text + "\n", encoding="utf-8")
    record = {
        "run": run_id,
        "level": report.level,
        "checks": [dataclasses.asdict(c) for c in report.checks],
    }
    (run_dir / "report.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    prune(args.state_dir / "runs", KEEP_RUNS)
    return report.level, text


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="The weekly quality run.")
    parser.add_argument(
        "--quiet-ok", action="store_true", help="print nothing when all pass"
    )
    parser.add_argument("--seeds", type=int, default=DEFAULT_SEEDS)
    parser.add_argument("--mutation-modules", type=int, default=PER_WEEK)
    parser.add_argument("--reps", type=int, default=REPS, help="benchmark rounds")
    parser.add_argument("--only", help=f"comma-separated subset of {','.join(JOBS)}")
    parser.add_argument("--budget-min", type=float, default=BUDGET_S / 60)
    parser.add_argument(
        "--load-max",
        type=float,
        default=Limits().load_max,
        help="a job starts only below this 1-minute load",
    )
    parser.add_argument(
        "--rebaseline", action="store_true", help="record a new bench baseline"
    )
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    parser.add_argument(
        "--ref", default="origin/master", help="what the clone checks out"
    )
    parser.add_argument("--prepared", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    args.clone = args.state_dir / "checkout"
    return args


def main(
    argv: Sequence[str] | None = None,
    host: Host | None = None,
    execv: Callable[[str, list[str]], object] = os.execv,
) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(raw)
    os.environ.update(user_bus_env(os.environ))  # cron has no user bus variables
    host = host or default_host()
    if not args.prepared:
        stamp = time.strftime("%Y%m%dT%H%M%S", time.localtime(host.now()))
        commit, problem = prepare(host, stamp, args.clone, args.ref)
        if problem:
            print(f"ALERT: weekly quality run: {problem}; nothing ran")
            return 0
        os.environ["BINNACLE_WEEKLY_COMMIT"] = commit
        python = str(args.clone / ".venv" / "bin" / "python")
        execv(
            python,
            [
                python,
                str(args.clone / "scripts" / "weekly_quality.py"),
                "--prepared",
                *raw,
            ],
        )
        return 0  # only a test's execv returns
    level, text = run(args, host, dict(os.environ))
    if not (args.quiet_ok and level == "ok"):
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
