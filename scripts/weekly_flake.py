"""The weekly flake hunt (scripts/weekly_quality.py).

The full suite runs once per seed, each run with its own pytest-randomly
seed, in the two lanes of scripts/run_test_suite.py: the parallel-safe lane
with four xdist workers, which share the scope's one CPU (the load the hunt
needs, created only inside its own scope), and the ordinary-process lane.
Each lane writes a junit XML and a log into the run's directory, so no
failure is lost, and the report names each failing test with its seed.
master's CI passed before the weekly run sees a commit, so a failure here
is a test that depends on load, order or timing: fix or quarantine it
within a week.
"""

from __future__ import annotations

import random
import xml.etree.ElementTree as ET  # nosec B405 - parses our own pytest's junit XML
from pathlib import Path

from scripts.run_test_suite import build_pytest_lane_command
from scripts.smoke_checks import Check
from scripts.weekly_scope import Outcome, Runner

WORKERS = 4
LANE_TIMEOUT_S = {"main": 1500, "ordinary": 600}
DEFAULT_SEEDS = 5


def seeds_for(run_id: str, count: int) -> list[int]:
    """The run's seeds: fixed by the run id, so a report can be replayed."""
    rng = random.Random(run_id)  # nosec B311 - test ordering, not security
    return [rng.randrange(1, 2**31) for _ in range(count)]


def lane_argv(lane: str, seed: int, xml: Path) -> list[str]:
    return build_pytest_lane_command(
        test_args=["tests"],
        workers=WORKERS,
        seed=seed,
        shared_args=[f"--junitxml={xml}", "-p", "no:cacheprovider"],
        no_xdist=lane == "ordinary",
    )


def junit_failures(xml: Path) -> tuple[int, list[str]]:
    """(tests run, failing test ids) from a junit XML file."""
    root = ET.parse(xml).getroot()  # nosec B314 - written by our own pytest run
    tests, failing = 0, []
    for case in root.iter("testcase"):
        tests += 1
        if case.find("failure") is not None or case.find("error") is not None:
            failing.append(f"{case.get('classname')}::{case.get('name')}")
    return tests, failing


def lane_result(
    seed: int, lane: str, outcome: Outcome, xml: Path
) -> tuple[str, str, int]:
    """(level, detail, tests) for one lane of one seed."""
    tests, failing = junit_failures(xml) if xml.exists() else (0, [])
    where = f"seed {seed} {lane}"
    if failing:
        shown = ", ".join(failing[:5]) + (
            f" and {len(failing) - 5} more" if len(failing) > 5 else ""
        )
        return "warn", f"{where}: {len(failing)} failed: {shown}", tests
    if outcome.status == "ok":
        return "ok", f"{where}: {tests} passed", tests
    if outcome.status in ("aborted", "skipped"):  # this seed was not tested
        return "warn", f"{where}: {outcome.status} ({outcome.detail})", tests
    if outcome.status == "timeout":
        return (
            "warn",
            f"{where}: timed out after {outcome.seconds:.0f} s (a hang?)",
            tests,
        )
    return (
        "warn",
        f"{where}: {outcome.status} without a failing test ({outcome.detail}); see the log",
        tests,
    )


def flake_hunt(runner: Runner, clone: Path, seeds: list[int]) -> list[Check]:
    """Run every seed's two lanes; one check per seed plus a summary."""
    out_dir = runner.run_dir / "flake"
    out_dir.mkdir(parents=True, exist_ok=True)
    checks, completed, failures = [], 0, 0
    for seed in seeds:
        levels, details, done = [], [], True
        for lane in ("main", "ordinary"):
            xml = out_dir / f"seed-{seed}-{lane}.xml"
            outcome = runner.execute(
                f"flake-{seed}-{lane}",
                lane_argv(lane, seed, xml),
                LANE_TIMEOUT_S[lane],
                clone,
            )
            level, detail, _ = lane_result(seed, lane, outcome, xml)
            levels.append(level)
            details.append(detail)
            done = done and outcome.status in ("ok", "failed", "timeout")
            if outcome.status in ("aborted", "skipped"):
                break  # the next lane would meet the same busy server
        worst = "warn" if "warn" in levels else "ok"
        failures += worst == "warn"
        completed += done
        checks.append(Check(f"flake seed {seed}", worst, "; ".join(details)))
    level = "warn" if failures or not completed else "ok"
    summary = f"{completed} of {len(seeds)} seeds completed, {failures} with a finding"
    if not completed:
        summary += " (no seed ran to the end)"
    checks.append(
        Check("flake hunt", level, f"{summary}; junit and logs under {runner.run_dir}")
    )
    return checks
