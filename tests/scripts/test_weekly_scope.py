"""scripts/weekly_scope.py: the scope command line, the quiet gate, the job
watch (abort on production calls or memory, timeout, stragglers) and the
runner's gate, budget and one retry. Everything runs on a fake host."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.weekly_scope import (
    Job,
    Limits,
    Runner,
    Samples,
    gate_reason,
    probe_scope,
    run_job,
    scope_argv,
    unit_name,
    wait_for_gate,
)
from tests.scripts.weekly_fakes import T0, FakeHost, inner, stops

LIMITS = Limits()


def job(tmp_path: Path, timeout_s: int = 600) -> Job:
    return Job(
        "flake-1-main", ["pytest", "tests"], tmp_path, tmp_path / "x.log", timeout_s, {}
    )


def test_scope_argv_limits_cpu_tasks_runtime_and_priority() -> None:
    argv = scope_argv("binnacle-weekly-r-x", 600, ["pytest", "-q"])
    assert argv[:5] == ["systemd-run", "--user", "--scope", "--quiet", "--collect"]
    assert "--unit=binnacle-weekly-r-x" in argv
    for prop in (
        "CPUQuota=100%",
        "CPUWeight=idle",
        "MemoryMax=2G",
        "TasksMax=1024",
        "RuntimeMaxSec=690",
    ):
        assert prop in argv
    tail = argv[argv.index("--") + 1 :]
    assert tail == [
        "nice",
        "-n",
        "19",
        "ionice",
        "-c3",
        "timeout",
        "-k",
        "30",
        "600",
        "pytest",
        "-q",
    ]
    assert inner(argv) == ["pytest", "-q"]


def test_unit_names_carry_the_run_and_the_job() -> None:
    assert unit_name("20260928T0010", "bench") == "binnacle-weekly-20260928T0010-bench"


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({}, ""),
        ({"calls_at": [T0 - 60]}, "1 production tool call(s) in the last 300 s"),
        ({"load": 2.5}, "load 2.50 >= 2"),
        ({"mem_kb": 1024 * 1024}, "MemAvailable 1024 MiB < 3072 MiB"),
    ],
)
def test_the_gate_needs_quiet_low_load_and_memory(change: dict, reason: str) -> None:
    host = FakeHost(**change)
    assert gate_reason(host.as_host(), LIMITS) == reason


def test_a_call_older_than_the_quiet_window_does_not_close_the_gate() -> None:
    host = FakeHost(calls_at=[T0 - 301])
    assert gate_reason(host.as_host(), LIMITS) == ""


def test_waiting_for_the_gate_ends_when_production_goes_quiet() -> None:
    host = FakeHost(calls_at=[T0 - 10])
    assert wait_for_gate(host.as_host(), LIMITS, T0 + 3600) == ""
    assert host.t >= T0 + 290  # the call left the 300 s window


def test_waiting_for_the_gate_gives_up_at_the_deadline() -> None:
    host = FakeHost(load=3.0)
    reason = wait_for_gate(host.as_host(), LIMITS, T0 + 100)
    assert reason.startswith("load 3.00") and host.t <= T0 + 100


@pytest.mark.parametrize(
    ("rc", "status"), [(0, "ok"), (1, "failed"), (124, "timeout"), (137, "timeout")]
)
def test_a_finished_job_reports_its_exit(tmp_path: Path, rc: int, status: str) -> None:
    host = FakeHost(plans=[(95.0, rc, None)])
    outcome = run_job(host.as_host(), LIMITS, job(tmp_path), "u1", Samples())
    assert outcome.status == status and outcome.rc == rc
    assert 95.0 <= outcome.seconds <= 98.0
    assert stops(host) == ["u1.scope"]  # stragglers die with the scope


def test_a_production_call_stops_the_job_by_its_exact_unit(tmp_path: Path) -> None:
    host = FakeHost(plans=[(3600.0, 0, None)], calls_at=[T0 + 70])
    samples = Samples()
    outcome = run_job(
        host.as_host(), LIMITS, job(tmp_path), "binnacle-weekly-r-flake", samples
    )
    assert outcome.status == "aborted"
    assert outcome.detail == "server busy: 1 production tool call(s)"
    assert stops(host) == ["binnacle-weekly-r-flake.scope"]
    assert host.procs[0].killed and samples.busy_aborts == 1
    assert 70.0 <= outcome.seconds <= 82.0  # the first 10 s check after the call


def test_the_scope_memory_cap_stops_the_job(tmp_path: Path) -> None:
    host = FakeHost(plans=[(3600.0, 0, None)], rss_kb=3 * 1024 * 1024)
    outcome = run_job(host.as_host(), LIMITS, job(tmp_path), "u2", Samples())
    assert (
        outcome.status == "aborted"
        and outcome.detail == "scope memory 3072 MiB > 2048 MiB"
    )


def test_low_host_memory_stops_the_job(tmp_path: Path) -> None:
    host = FakeHost(plans=[(3600.0, 0, None)], mem_kb=512 * 1024)
    outcome = run_job(host.as_host(), LIMITS, job(tmp_path), "u3", Samples())
    assert outcome.status == "aborted" and outcome.detail.startswith("host memory low")


def test_a_job_past_its_deadline_is_stopped_by_the_runner(tmp_path: Path) -> None:
    host = FakeHost(plans=[(10_000.0, 0, None)])
    outcome = run_job(
        host.as_host(), LIMITS, job(tmp_path, timeout_s=100), "u4", Samples()
    )
    assert outcome.status == "aborted" and outcome.detail == "past its deadline"


def test_samples_record_load_and_memory_at_every_check(tmp_path: Path) -> None:
    host = FakeHost(plans=[(125.0, 0, None)], load=1.5)
    samples = Samples()
    run_job(host.as_host(), LIMITS, job(tmp_path), "u5", samples)
    assert samples.load == [1.5] * 12
    assert samples.summary().startswith(
        "load1 median 1.50 max 1.50; MemAvailable min 8192 MiB"
    )


def test_a_job_that_cannot_start_is_an_error(tmp_path: Path) -> None:
    host = FakeHost()

    def refuse(*args: object) -> None:
        raise OSError("no such file")

    fake = host.as_host()
    fake.spawn = refuse  # type: ignore[assignment]
    outcome = run_job(fake, LIMITS, job(tmp_path), "u6", Samples())
    assert outcome.status == "error" and "no such file" in outcome.detail


@pytest.mark.parametrize(
    ("result", "problem"),
    [
        ((0, "100000 100000\n1\n"), ""),
        (
            (0, "max 100000\n1\n"),
            "the CPU settings are not in force (cpu.max, cpu.idle: 'max 100000 1')",
        ),
        (
            (0, "100000 100000\n0\n"),
            "the CPU settings are not in force (cpu.max, cpu.idle: '100000 100000 0')",
        ),
        (
            (1, "Failed to connect to bus"),
            "systemd-run --user --scope failed (exit 1): Failed to connect to bus",
        ),
    ],
)
def test_the_probe_checks_that_both_cpu_settings_hold(
    tmp_path: Path, result: tuple[int, str], problem: str
) -> None:
    host = FakeHost(run_results={"cpu.max": result})
    assert probe_scope(host.as_host(), "r", tmp_path / "probe.log") == problem
    assert "--unit=binnacle-weekly-r-probe" in host.ran[0]


def runner(host: FakeHost, tmp_path: Path, budget_s: float = 10_800.0) -> Runner:
    return Runner(host.as_host(), LIMITS, "r", tmp_path, {}, deadline=T0 + budget_s)


def test_the_runner_retries_once_after_production_calls(tmp_path: Path) -> None:
    host = FakeHost(plans=[(3600.0, 0, None), (50.0, 0, None)], calls_at=[T0 + 40])
    run = runner(host, tmp_path)
    outcome = run.execute("bench", ["python", "bench.py"], 900, tmp_path)
    assert outcome.status == "ok" and len(host.spawned) == 2
    assert "--unit=binnacle-weekly-r-bench-retry" in host.spawned[1]
    assert run.timeline[0].startswith("bench: aborted") and run.timeline[1].startswith(
        "bench: ok"
    )


def test_the_runner_skips_a_job_when_no_quiet_moment_comes(tmp_path: Path) -> None:
    host = FakeHost(load=3.0)
    run = runner(host, tmp_path)
    run.gate_wait_s = 600
    outcome = run.execute("usage", ["python", "u.py"], 900, tmp_path)
    assert outcome.status == "skipped" and outcome.detail.startswith(
        "no quiet moment: load 3.00"
    )
    assert host.spawned == []


def test_the_runner_skips_a_job_that_no_longer_fits_the_budget(tmp_path: Path) -> None:
    host = FakeHost()
    outcome = runner(host, tmp_path, budget_s=60).execute(
        "mutation", ["m"], 3600, tmp_path
    )
    assert (
        outcome.status == "skipped" and outcome.detail == "no time left in the budget"
    )


def test_the_runner_trims_a_timeout_to_the_budget(tmp_path: Path) -> None:
    host = FakeHost(plans=[(5.0, 0, None)])
    runner(host, tmp_path, budget_s=1000).execute("flake", ["pytest"], 3600, tmp_path)
    tail = host.spawned[0][host.spawned[0].index("timeout") :]
    assert tail[:4] == ["timeout", "-k", "30", "1000"]
