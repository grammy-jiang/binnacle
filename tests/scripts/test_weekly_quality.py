"""scripts/weekly_quality.py and weekly_host.py: preparing the clone, the
re-exec into it, the isolation probe, the report, --quiet-ok, pruning and
the jobs' environment. The jobs themselves are faked."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import scripts.weekly_quality as wq
from scripts.smoke_checks import Check
from scripts.weekly_host import job_env, user_bus_env
from tests.scripts.weekly_fakes import FakeHost


@pytest.fixture(autouse=True)
def restored_environ(monkeypatch: Any) -> None:
    """main() writes these into os.environ; monkeypatch puts them back."""
    for key in (
        "XDG_RUNTIME_DIR",
        "DBUS_SESSION_BUS_ADDRESS",
        "BINNACLE_WEEKLY_COMMIT",
    ):
        monkeypatch.setenv(key, wq.os.environ.get(key, "unset-by-test"))


def test_the_prepare_script_clones_once_and_checks_out_the_ref(tmp_path: Path) -> None:
    fresh = wq.prepare_script(
        tmp_path / "clone", "https://example/x.git", "origin/master"
    )
    assert fresh.startswith("set -e && git clone -q https://example/x.git ")
    (tmp_path / "clone" / ".git").mkdir(parents=True)
    again = wq.prepare_script(
        tmp_path / "clone", "https://example/x.git", "origin/feature/a"
    )
    assert "git clone" not in again
    for step in (
        "git fetch -q origin",
        "git checkout -q --force --detach origin/feature/a",
        "git clean -qfdx -e .venv",
        "sync -q --frozen",
    ):
        assert step in again


def test_main_prepares_the_clone_in_a_scope_and_runs_its_copy(
    tmp_path: Path, monkeypatch: Any
) -> None:
    host = FakeHost(run_results={"git rev-parse": (0, "7d90f7f\n")})
    calls: list[tuple[str, list[str]]] = []
    rc = wq.main(
        ["--state-dir", str(tmp_path), "--quiet-ok"],
        host=host.as_host(),
        execv=lambda path, argv: calls.append((path, argv)),
    )
    assert rc == 0
    assert host.ran[0][:3] == ["systemd-run", "--user", "--scope"]
    python = str(tmp_path / "checkout" / ".venv" / "bin" / "python")
    assert calls == [
        (
            python,
            [
                python,
                str(tmp_path / "checkout" / "scripts" / "weekly_quality.py"),
                "--prepared",
                "--state-dir",
                str(tmp_path),
                "--quiet-ok",
            ],
        )
    ]
    assert wq.os.environ["BINNACLE_WEEKLY_COMMIT"] == "7d90f7f"


def test_a_failed_prepare_is_an_alert_and_runs_nothing(
    tmp_path: Path, capsys: Any
) -> None:
    host = FakeHost(run_results={"git rev-parse": (1, "fatal: unable to access")})
    calls: list[Any] = []
    rc = wq.main(
        ["--state-dir", str(tmp_path)],
        host=host.as_host(),
        execv=lambda *a: calls.append(a),
    )
    out = capsys.readouterr().out
    assert rc == 0 and calls == []
    assert out.startswith(
        "ALERT: weekly quality run: could not update the clone (exit 1)"
    )


def test_a_failed_isolation_probe_runs_no_job(tmp_path: Path, capsys: Any) -> None:
    host = FakeHost(run_results={"cpu.max": (1, "Failed to connect to bus")})
    rc = wq.main(["--prepared", "--state-dir", str(tmp_path)], host=host.as_host())
    out = capsys.readouterr().out
    assert rc == 0 and host.spawned == []
    assert out.startswith(
        "ALERT: isolation: systemd-run --user --scope failed (exit 1)"
    )


def fake_jobs(monkeypatch: Any, level: str = "ok") -> list[str]:
    seen: list[str] = []

    def job(name: str):
        def run(*args: Any, **kwargs: Any) -> list[Check]:
            seen.append(name)
            return [Check(name, level, "fake")]

        return run

    for name in ("usage_checks", "bench_checks", "flake_hunt", "mutation_rotation"):
        monkeypatch.setattr(wq, name, job(name))
    return seen


def test_a_clean_run_is_silent_with_quiet_ok_and_keeps_its_report(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    seen = fake_jobs(monkeypatch)
    host = FakeHost(run_results={"cpu.max": (0, "100000 100000\n1\n")})
    wq.main(
        ["--prepared", "--quiet-ok", "--state-dir", str(tmp_path)], host=host.as_host()
    )
    assert capsys.readouterr().out == ""
    assert seen == ["usage_checks", "bench_checks", "flake_hunt", "mutation_rotation"]
    (run_dir,) = (tmp_path / "runs").iterdir()
    text = (run_dir / "report.txt").read_text()
    assert text.startswith("OK: weekly quality run passed (6 checks)")
    assert (
        "\nTimeline:\n" in text
        and "\nImpact:\n" in text
        and f"History: {run_dir / 'report.txt'}" in text
    )
    assert json.loads((run_dir / "report.json").read_text())["level"] == "ok"


def test_a_warning_is_printed_with_its_summary(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    fake_jobs(monkeypatch, level="warn")
    host = FakeHost(run_results={"cpu.max": (0, "100000 100000\n1\n")})
    wq.main(
        [
            "--prepared",
            "--quiet-ok",
            "--only",
            "usage,flake",
            "--state-dir",
            str(tmp_path),
        ],
        host=host.as_host(),
    )
    first = capsys.readouterr().out.splitlines()[0]
    assert first == "WARN: usage_checks: fake; flake_hunt: fake"


def test_prune_keeps_the_newest_runs(tmp_path: Path) -> None:
    for i in range(10):
        (tmp_path / f"2026092{i}T0010").mkdir()
    wq.prune(tmp_path, 8)
    assert min(p.name for p in tmp_path.iterdir()) == "20260922T0010"
    assert len(list(tmp_path.iterdir())) == 8


def test_the_user_bus_variables_are_filled_in_for_cron() -> None:
    env = user_bus_env({"PATH": "/usr/bin"})
    assert env["XDG_RUNTIME_DIR"].startswith("/run/user/")
    assert env["DBUS_SESSION_BUS_ADDRESS"] == f"unix:path={env['XDG_RUNTIME_DIR']}/bus"
    kept = user_bus_env(
        {"XDG_RUNTIME_DIR": "/run/user/7", "DBUS_SESSION_BUS_ADDRESS": "x"}
    )
    assert kept["DBUS_SESSION_BUS_ADDRESS"] == "x"


def test_jobs_see_the_defaults_and_never_the_job_manager(tmp_path: Path) -> None:
    env = job_env(
        {"PATH": "/usr/bin:/bin", "BINNACLE_MANAGED_DEPLOYMENT": "1"}, tmp_path
    )
    assert "BINNACLE_MANAGED_DEPLOYMENT" not in env
    assert Path(env["BINNACLE_CONFIG_FILE"]).read_text() == ""
    assert env["PATH"].split(":")[0].endswith("/.local/bin")


@pytest.mark.parametrize("only", ["usage", "bench,mutation"])
def test_only_selects_jobs(tmp_path: Path, monkeypatch: Any, only: str) -> None:
    seen = fake_jobs(monkeypatch)
    host = FakeHost(run_results={"cpu.max": (0, "100000 100000\n1\n")})
    wq.main(
        ["--prepared", "--quiet-ok", "--only", only, "--state-dir", str(tmp_path)],
        host=host.as_host(),
    )
    assert [s.split("_")[0] for s in seen] == only.split(",")
