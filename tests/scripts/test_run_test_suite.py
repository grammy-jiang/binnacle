from __future__ import annotations

import subprocess
import sys

import pytest

from scripts import run_test_suite as runner


def _mock_subprocess(monkeypatch, returncodes: list[int]) -> list[list[str]]:
    commands: list[list[str]] = []
    codes = iter(returncodes)

    def fake_run(command, *, check):
        assert check is False
        command = list(command)
        commands.append(command)
        return subprocess.CompletedProcess(command, next(codes))

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    return commands


def test_worker_resolution_uses_cli_then_environment_then_bounded_default(
    monkeypatch,
):
    monkeypatch.setattr(runner.os, "cpu_count", lambda: 99)

    assert runner.resolve_workers(2, {runner.WORKER_ENV: "3"}) == 2
    assert runner.resolve_workers(None, {runner.WORKER_ENV: "3"}) == 3
    assert 1 <= runner.resolve_workers(None, {}) <= 4
    assert runner.resolve_workers(None, {}) == 4


@pytest.mark.parametrize("value", ["0", "-1", "not-an-int"])
def test_cli_rejects_invalid_worker_values(value):
    with pytest.raises(SystemExit) as exc:
        runner.main(["--workers", value], environ={})

    assert exc.value.code == 2


@pytest.mark.parametrize("value", ["0", "-1", "not-an-int"])
def test_environment_rejects_invalid_worker_values(value):
    with pytest.raises(SystemExit) as exc:
        runner.main([], environ={runner.WORKER_ENV: value})

    assert exc.value.code == 2


def test_worker_one_omits_xdist_and_keeps_marker_split():
    main, ordinary = runner.build_lane_commands(
        workers=1,
        seed=None,
        shared_args=[],
    )

    assert main[:5] == [sys.executable, "-m", "pytest", "tests", "-q"]
    assert ordinary[:5] == [sys.executable, "-m", "pytest", "tests", "-q"]
    assert main[5:7] == ["-m", "not no_xdist"]
    assert ordinary[5:7] == ["-m", "no_xdist"]
    assert "-n" not in main
    assert "--dist=worksteal" not in main
    assert "-n" not in ordinary
    assert "--dist=worksteal" not in ordinary


def test_parallel_lane_gets_xdist_seed_and_shared_args_only_where_required():
    shared = ["--ignore=tests/integration/test_wheel_artifact.py"]
    main, ordinary = runner.build_lane_commands(
        workers=4,
        seed=12345,
        shared_args=shared,
    )

    assert ["-n", "4"] == main[7:9]
    assert "--dist=worksteal" in main
    assert "-n" not in ordinary
    assert "--dist=worksteal" not in ordinary
    assert "--randomly-seed=12345" in main
    assert "--randomly-seed=12345" in ordinary
    assert shared[0] in main
    assert shared[0] in ordinary


@pytest.mark.parametrize(
    ("returncodes", "expected"),
    [
        ([7, 0], 1),
        ([0, 5], 1),
        ([0, 0], 0),
    ],
)
def test_both_lanes_run_and_any_lane_failure_makes_final_exit_nonzero(
    monkeypatch,
    returncodes,
    expected,
):
    commands = _mock_subprocess(monkeypatch, returncodes)

    assert runner.main(["--workers", "1", "--seed", "12345"], environ={}) == expected
    assert len(commands) == 2
    assert "not no_xdist" in commands[0]
    assert "no_xdist" in commands[1]


def test_main_reports_commands_lane_results_total_and_workers(monkeypatch, capsys):
    _mock_subprocess(monkeypatch, [0, 0])

    assert (
        runner.main(
            [
                "--workers",
                "2",
                "--seed",
                "12345",
                "--ignore=tests/integration/test_wheel_artifact.py",
            ],
            environ={},
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "parallel-safe lane command:" in output
    assert "ordinary-process lane command:" in output
    assert output.count("exit code: 0") == 2
    assert output.count("elapsed:") >= 3
    assert "total elapsed:" in output
    assert "resolved workers: 2" in output
