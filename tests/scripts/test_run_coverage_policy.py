from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts import run_coverage_policy as runner


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


def _pipeline(
    *,
    workers: int = 1,
    shared_args: list[str] | None = None,
) -> list[list[str]]:
    named = runner.build_pipeline_commands(
        workers=workers,
        seed=12345,
        unit_json=Path("/tmp/unit.json"),
        full_json=Path("/tmp/full.json"),
        shared_args=shared_args or [],
    )
    return [command for _, command in named]


def test_pipeline_order_preserves_unit_report_boundary_and_append_semantics():
    shared = ["--ignore=tests/integration/test_wheel_artifact.py"]
    commands = _pipeline(shared_args=shared)

    assert commands[0] == [sys.executable, "-m", "coverage", "erase"]

    unit_main, unit_ordinary = commands[1:3]
    assert "tests/unit" in unit_main
    assert "tests/unit" in unit_ordinary
    assert "not no_xdist" in unit_main
    assert "no_xdist" in unit_ordinary
    assert "--cov-append" not in unit_main
    assert "--cov-append" in unit_ordinary

    assert commands[3] == [
        sys.executable,
        "-m",
        "coverage",
        "json",
        "--fail-under=0",
        "-o",
        "/tmp/unit.json",
    ]

    nonunit_main, nonunit_ordinary = commands[4:6]
    for command in (nonunit_main, nonunit_ordinary):
        assert "tests" in command
        assert "--ignore=tests/unit" in command
        assert "--cov-append" in command

    assert "not no_xdist" in nonunit_main
    assert "no_xdist" in nonunit_ordinary
    assert commands[6] == [
        sys.executable,
        "-m",
        "coverage",
        "json",
        "--fail-under=0",
        "-o",
        "/tmp/full.json",
    ]

    pytest_commands = commands[1:3] + commands[4:6]
    for command in pytest_commands:
        assert "--cov=binnacle" in command
        assert "--cov-branch" in command
        assert "--cov-fail-under=0" in command
        assert "--cov-report=" in command
        assert "--randomly-seed=12345" in command
        assert shared[0] in command


def test_workers_only_add_xdist_to_parallel_safe_coverage_lanes():
    commands = _pipeline(workers=4)

    for index in (1, 4):
        command = commands[index]
        xdist_index = command.index("-n")
        assert ["-n", "4"] == command[xdist_index : xdist_index + 2]
        assert "--dist=worksteal" in command

    for index in (2, 5):
        assert "-n" not in commands[index]
        assert "--dist=worksteal" not in commands[index]


def test_failure_stops_pipeline_without_running_later_commands(monkeypatch):
    commands = _mock_subprocess(monkeypatch, [0, 0, 7])

    assert (
        runner.main(
            [
                "--workers",
                "1",
                "--seed",
                "12345",
                "--unit-json",
                "/tmp/unit.json",
                "--full-json",
                "/tmp/full.json",
            ],
            environ={},
        )
        == 7
    )

    assert len(commands) == 3
    assert commands[0] == [sys.executable, "-m", "coverage", "erase"]
    assert "tests/unit" in commands[1]
    assert "tests/unit" in commands[2]


def test_main_runs_all_seven_pipeline_commands(monkeypatch):
    commands = _mock_subprocess(monkeypatch, [0] * 7)

    assert (
        runner.main(
            [
                "--workers",
                "1",
                "--seed",
                "12345",
                "--unit-json",
                "/tmp/unit.json",
                "--full-json",
                "/tmp/full.json",
                "--ignore=tests/integration/test_wheel_artifact.py",
            ],
            environ={},
        )
        == 0
    )

    assert len(commands) == 7
