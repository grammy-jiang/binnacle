"""scripts/weekly_bench.py and weekly_bench_checks.py: the fixtures, the
temporary server's configuration, the fixed cases, percentiles and the
baseline comparison. No server is started."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from scripts.weekly_bench import build_fixtures, cases, config_text, free_port
from scripts.weekly_bench_checks import bench_checks, compare, percentile, summarize
from scripts.weekly_scope import Limits, Runner
from tests.scripts.weekly_fakes import T0, FakeHost, inner


def test_fixtures_are_the_same_every_week(tmp_path: Path) -> None:
    build_fixtures(tmp_path / "a")
    build_fixtures(tmp_path / "b")
    files = sorted(
        p.relative_to(tmp_path / "a")
        for p in (tmp_path / "a").rglob("*")
        if p.is_file()
    )
    assert len(files) == 202
    for rel in files:
        assert (tmp_path / "a" / rel).read_bytes() == (
            tmp_path / "b" / rel
        ).read_bytes()


def test_the_config_isolates_roots_token_spool_and_owner(tmp_path: Path) -> None:
    text = config_text(tmp_path, tmp_path / "work", 18_123)
    tomllib = pytest.importorskip("tomllib")
    cfg = tomllib.loads(text)
    assert cfg["roots"] == {"default_root": str(tmp_path / "work"), "extra_roots": []}
    assert cfg["auth"]["token_file"] == str(tmp_path / "token")
    assert cfg["serve"] == {"host": "127.0.0.1", "port": 18_123}
    assert cfg["jobs"]["owner"] == "embedded"
    assert cfg["jobs"]["dir"].startswith(str(tmp_path))
    assert cfg["run_command"]["auto_background_evidence_dir"].startswith(str(tmp_path))


def test_the_cases_are_fixed_and_stay_in_the_workdir(tmp_path: Path) -> None:
    round_1 = cases(tmp_path, 1)
    assert [c[0] for c in round_1] == [
        "read_file-small",
        "read_file-range",
        "list_files-glob",
        "search_text-literal",
        "search_text-regex",
        "write_file",
        "edit_file",
        "run_command-fast",
        "job_status-listing",
    ]
    for _, _, args in round_1:
        for key in ("path", "workdir"):
            if key in args:
                assert args[key].startswith(str(tmp_path))


def test_free_port_is_a_bindable_local_port() -> None:
    assert 1024 < free_port() < 65536


def test_percentiles_and_summary() -> None:
    assert percentile([], 0.5) == 0.0
    values = [float(v) for v in range(1, 21)]
    assert percentile(values, 0.50) == 10.0 and percentile(values, 0.95) == 19.0
    assert summarize({"a": values}) == {"a": {"p50_ms": 10.0, "p95_ms": 19.0, "n": 20}}


def test_compare_warns_above_the_ratio_plus_slack() -> None:
    base = {"a": {"p50_ms": 8.0, "p95_ms": 10.0}, "b": {"p50_ms": 8.0, "p95_ms": 10.0}}
    now = {
        "a": {"p50_ms": 9.0, "p95_ms": 17.0},
        "b": {"p50_ms": 9.0, "p95_ms": 17.6},
        "c": {"p50_ms": 1.0, "p95_ms": 2.0},
    }
    checks = {c.name: c for c in compare(now, base)}
    assert checks["bench a"].level == "ok"  # limit 10 * 1.25 + 5 = 17.5
    assert checks["bench b"].level == "warn"
    assert checks["bench c"].level == "ok" and "no baseline" in checks["bench c"].detail


def fake_bench(times: dict[str, list[float]], errors: dict[str, str] | None = None):
    def effect(argv: Sequence[str]) -> None:
        args = inner(argv)
        out = Path(args[args.index("--out") + 1])
        data = {
            "reps": 3,
            "startup_s": 2.5,
            "rss_kb": 150_000,
            "cases": times,
            "errors": errors or {},
        }
        out.write_text(json.dumps(data), encoding="utf-8")

    return effect


def runner(host: FakeHost, tmp_path: Path) -> Runner:
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    return Runner(host.as_host(), Limits(), "r1", run_dir, {}, deadline=T0 + 10_800)


def test_the_first_run_records_the_baseline_then_compares(tmp_path: Path) -> None:
    fast = {"read_file-small": [10.0, 11.0, 12.0]}
    slow = {"read_file-small": [30.0, 31.0, 32.0]}
    host = FakeHost(plans=[(60.0, 0, fake_bench(fast)), (60.0, 0, fake_bench(slow))])
    first = bench_checks(
        runner(host, tmp_path), tmp_path, tmp_path, 3, rebaseline=False
    )
    assert first[0].detail.startswith("baseline recorded (1 cases); 3 rounds")
    assert (
        json.loads((tmp_path / "bench-baseline.json").read_text())["cases"][
            "read_file-small"
        ]["p95_ms"]
        == 12.0
    )
    argv = inner(host.spawned[0])
    assert argv[0] == sys.executable and argv[1].endswith("scripts/weekly_bench.py")
    assert argv[argv.index("--workdir") + 1] == "/tmp/binnacle-bench-r1"
    second = bench_checks(
        runner(host, tmp_path), tmp_path, tmp_path, 3, rebaseline=False
    )
    assert second[1].level == "warn" and "baseline p95 12.0" in second[1].detail


def test_call_errors_and_a_failed_run_are_warnings(tmp_path: Path) -> None:
    host = FakeHost(
        plans=[(60.0, 0, fake_bench({}, {"stop_job": "boom"})), (60.0, 1, None)]
    )
    checks = bench_checks(
        runner(host, tmp_path), tmp_path, tmp_path, 3, rebaseline=False
    )
    assert checks[0].level == "warn" and checks[0].detail == "stop_job failed: boom"
    failed = bench_checks(
        runner(host, tmp_path), tmp_path, tmp_path, 3, rebaseline=False
    )
    assert failed[0].level == "warn" and failed[0].detail.startswith("failed (exit 1)")


def test_a_bench_that_found_no_quiet_moment_is_a_warning(tmp_path: Path) -> None:
    host = FakeHost(plans=[(3600.0, 0, None)], calls_at=[T0 + 20, T0 + 100])
    run = runner(host, tmp_path)
    run.gate_wait_s = 30
    checks = bench_checks(run, tmp_path, tmp_path, 3, rebaseline=False)
    assert checks[0].level == "warn" and checks[0].detail.startswith(
        "skipped (no quiet moment"
    )
