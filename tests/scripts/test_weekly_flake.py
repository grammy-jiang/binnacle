"""scripts/weekly_flake.py: seeds, the two lanes, junit parsing and the
report, with a fake host whose jobs write junit files."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from scripts.weekly_flake import (
    flake_hunt,
    junit_failures,
    lane_argv,
    lane_result,
    seeds_for,
)
from scripts.weekly_scope import Limits, Outcome, Runner
from tests.scripts.weekly_fakes import T0, FakeHost, inner

PASS = '<testsuite><testcase classname="tests.unit.a" name="test_ok"/></testsuite>'
FAIL = (
    "<testsuite>"
    '<testcase classname="tests.unit.a" name="test_ok"/>'
    '<testcase classname="tests.unit.b" name="test_flaky[2]"><failure message="x"/></testcase>'
    '<testcase classname="tests.unit.c" name="test_broken"><error message="y"/></testcase>'
    "</testsuite>"
)


def write_junit(text: str):
    def effect(argv: Sequence[str]) -> None:
        xml = next(
            a.removeprefix("--junitxml=")
            for a in inner(argv)
            if a.startswith("--junitxml=")
        )
        Path(xml).write_text(text, encoding="utf-8")

    return effect


def test_seeds_are_fixed_by_the_run_id() -> None:
    assert seeds_for("20260928T0010", 5) == seeds_for("20260928T0010", 5)
    assert seeds_for("20260928T0010", 5) != seeds_for("20261005T0010", 5)
    assert all(1 <= s < 2**31 for s in seeds_for("x", 20))


def test_the_lanes_follow_run_test_suite(tmp_path: Path) -> None:
    main = lane_argv("main", 7, tmp_path / "a.xml")
    assert main[:3] == [sys.executable, "-m", "pytest"]
    assert ["-m", "not no_xdist"] == main[main.index("-m", 3) : main.index("-m", 3) + 2]
    assert (
        "-n" in main
        and "--randomly-seed=7" in main
        and f"--junitxml={tmp_path / 'a.xml'}" in main
    )
    ordinary = lane_argv("ordinary", 7, tmp_path / "b.xml")
    assert "no_xdist" in ordinary and "-n" not in ordinary


def test_junit_failures_names_failed_and_errored_tests(tmp_path: Path) -> None:
    xml = tmp_path / "j.xml"
    xml.write_text(FAIL, encoding="utf-8")
    assert junit_failures(xml) == (
        3,
        ["tests.unit.b::test_flaky[2]", "tests.unit.c::test_broken"],
    )


def test_lane_results(tmp_path: Path) -> None:
    passed, failed = tmp_path / "p.xml", tmp_path / "f.xml"
    passed.write_text(PASS, encoding="utf-8")
    failed.write_text(FAIL, encoding="utf-8")
    ok = Outcome("ok", 0, 100.0)
    assert lane_result(9, "main", ok, passed) == ("ok", "seed 9 main: 1 passed", 1)
    level, detail, _ = lane_result(9, "main", Outcome("failed", 1, 100.0), failed)
    assert level == "warn" and detail.startswith(
        "seed 9 main: 2 failed: tests.unit.b::test_flaky[2]"
    )
    timeout = lane_result(
        9, "main", Outcome("timeout", 124, 1500.0), tmp_path / "none.xml"
    )
    assert timeout[0] == "warn" and "timed out after 1500 s" in timeout[1]
    crash = lane_result(
        9, "main", Outcome("failed", 2, 5.0, "exit 2"), tmp_path / "none.xml"
    )
    assert crash[0] == "warn" and "without a failing test" in crash[1]
    busy = lane_result(
        9,
        "main",
        Outcome("aborted", None, 50.0, "server busy: 1 production tool call(s)"),
        passed,
    )
    assert busy[0] == "warn"  # this seed was not tested


def runner(host: FakeHost, tmp_path: Path) -> Runner:
    return Runner(host.as_host(), Limits(), "r", tmp_path, {}, deadline=T0 + 10_800)


def test_a_flaky_test_is_reported_with_its_seed(tmp_path: Path) -> None:
    host = FakeHost(
        plans=[
            (60.0, 0, write_junit(PASS)),
            (30.0, 0, write_junit(PASS)),
            (60.0, 1, write_junit(FAIL)),
            (30.0, 0, write_junit(PASS)),
        ]
    )
    checks = flake_hunt(runner(host, tmp_path), tmp_path, [11, 22])
    assert [c.name for c in checks] == ["flake seed 11", "flake seed 22", "flake hunt"]
    assert checks[0].level == "ok" and checks[1].level == "warn"
    assert "seed 22 main: 2 failed: tests.unit.b::test_flaky[2]" in checks[1].detail
    assert checks[2].level == "warn" and checks[2].detail.startswith(
        "2 of 2 seeds completed, 1 with a finding"
    )
    assert sorted(p.name for p in (tmp_path / "flake").iterdir()) == [
        "seed-11-main.xml",
        "seed-11-ordinary.xml",
        "seed-22-main.xml",
        "seed-22-ordinary.xml",
    ]


def test_a_seed_stopped_by_production_skips_its_second_lane(tmp_path: Path) -> None:
    host = FakeHost(
        plans=[(3600.0, 0, None), (3600.0, 0, None)], calls_at=[T0 + 40, T0 + 400]
    )
    run = runner(host, tmp_path)
    run.gate_wait_s = 60  # the second try's gate then gives up
    checks = flake_hunt(run, tmp_path, [5])
    # stopped at the check after the call, then no quiet moment for the retry
    assert checks[0].level == "warn"
    assert checks[0].detail.startswith(
        "seed 5 main: skipped (no quiet moment: 1 production"
    )
    assert "ordinary" not in checks[0].detail and len(host.spawned) == 1
    assert checks[-1].level == "warn" and "no seed ran to the end" in checks[-1].detail


def test_all_seeds_clean_is_ok(tmp_path: Path) -> None:
    host = FakeHost(plans=[(60.0, 0, write_junit(PASS))] * 2)
    checks = flake_hunt(runner(host, tmp_path), tmp_path, [3])
    assert [c.level for c in checks] == ["ok", "ok"]
    assert checks[-1].detail.startswith("1 of 1 seeds completed, 0 with a finding")
