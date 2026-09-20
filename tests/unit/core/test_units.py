"""Managed unit mechanics: marker lines, rendering, diff, adopt, executable
resolution, the two doctor checks every owner shares, and the server unit."""

import os
import subprocess
from pathlib import Path

import pytest

from binnacle import server_unit, units

SPEC = units.UnitSpec(
    "x.service",
    "binnacle-x",
    "[Unit]\nDescription=x\n",
    {"bin": "/opt/x", "port": "8000"},
)


def test_marker_round_trip_quotes_values_with_spaces():
    spec = units.UnitSpec(
        "x.service", "binnacle-x", "[Unit]\n", {"repo": "/tmp/my repo", "p": "1"}
    )
    text = units.render(spec)
    assert text.startswith(
        "# Managed by binnacle (binnacle-x setup): repo='/tmp/my repo' p=1\n"
    )
    assert units.read_marker(text) == units.Marker(
        "binnacle-x", {"repo": "/tmp/my repo", "p": "1"}
    )


def test_marker_without_params_legacy_and_none():
    assert units.marker_line("binnacle", {}) == "# Managed by binnacle (binnacle setup)"
    assert units.read_marker(
        "# Managed by binnacle (binnacle setup)\n[Unit]\n"
    ) == units.Marker("binnacle", {})
    assert units.read_marker("# Managed by `binnacle setup`\n[Unit]\n") == units.Marker(
        "", {}, legacy=True
    )
    assert units.read_marker("[Unit]\nDescription=hand written\n") is None
    assert units.read_marker("") is None


def test_unit_diff_names_both_sides_and_is_empty_when_equal():
    assert units.unit_diff("a\nb\n", "a\nb\n", "x.service") == ""
    diff = units.unit_diff("a\nb\n", "a\nc\n", "x.service")
    assert (
        "--- x.service (on disk)" in diff
        and "+++ x.service (setup would write)" in diff
    )
    assert "-b" in diff and "+c" in diff
    assert units.unit_diff(None, "a\n", "x.service").startswith(
        "--- x.service (on disk)"
    )


def test_plan_write_create_unchanged_and_rewrite(tmp_path):
    path = tmp_path / "x.service"
    plan = units.plan_write(path, SPEC)
    assert (
        plan.action == "create" and plan.text == units.render(SPEC) and plan.diff == ""
    )
    path.write_text(plan.text)
    assert units.plan_write(path, SPEC).action == "unchanged"
    changed = units.UnitSpec(
        SPEC.name, SPEC.owner, "[Unit]\nDescription=y\n", SPEC.params
    )
    plan = units.plan_write(path, changed)
    assert plan.action == "rewrite"
    assert "-Description=x" in plan.diff and "+Description=y" in plan.diff


def test_plan_write_refuses_a_hand_written_unit_unless_adopted(tmp_path):
    path = tmp_path / "x.service"
    path.write_text("[Unit]\nDescription=hand written\n")
    plan = units.plan_write(path, SPEC)
    assert plan.action == "refuse"
    assert "no marker line" in plan.reason and "--adopt" in plan.reason
    assert "+# Managed by binnacle (binnacle-x setup)" in plan.diff
    assert units.plan_write(path, SPEC, adopt=True).action == "rewrite"


def test_plan_write_refuses_another_owners_unit_unless_adopted(tmp_path):
    path = tmp_path / "x.service"
    path.write_text(
        units.render(units.UnitSpec("x.service", "binnacle-y", SPEC.body, {}))
    )
    plan = units.plan_write(path, SPEC)
    assert plan.action == "refuse" and "`binnacle-y setup` manages it" in plan.reason
    assert units.plan_write(path, SPEC, adopt=True).action == "rewrite"


def test_plan_write_rewrites_a_legacy_marked_unit(tmp_path):
    path = tmp_path / "x.service"
    path.write_text("# Managed by `binnacle setup`\n" + SPEC.body)
    assert units.plan_write(path, SPEC).action == "rewrite"


def test_write_unit_backs_up_an_existing_file(tmp_path):
    path = tmp_path / "units" / "x.service"
    plan = units.plan_write(path, SPEC)
    assert units.write_unit(path, plan, tmp_path / "backups") is None
    assert path.read_text() == plan.text
    path.write_text("old\n")
    backup = units.write_unit(path, plan, tmp_path / "backups")
    assert backup is not None and backup.parent == tmp_path / "backups"
    assert backup.name.startswith("x.service.") and backup.read_text() == "old\n"
    assert path.read_text() == plan.text
    path.write_text("older\n")
    assert units.write_unit(path, plan) is None and path.read_text() == plan.text


def executable(tmp_path: Path, name: str) -> Path:
    exe = tmp_path / "bin" / name
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return exe


def test_resolve_executable_prefers_path_then_argv0(tmp_path, monkeypatch):
    exe = executable(tmp_path, "binnacle-x")
    assert (
        units.resolve_executable("binnacle-x", which=lambda n: str(exe))
        == exe.resolve()
    )
    monkeypatch.chdir(tmp_path)
    resolved = units.resolve_executable(
        "binnacle-x", argv0="bin/binnacle-x", which=lambda n: None
    )
    assert resolved == exe.resolve()
    monkeypatch.setattr(units.sys, "argv", ["bin/binnacle-x", "setup"])
    assert units.resolve_executable("binnacle-x", which=lambda n: None) == exe.resolve()


def test_resolve_executable_keeps_a_symlink_rather_than_its_target(tmp_path):
    target = executable(tmp_path / "versioned", "tunnel-client")
    link = tmp_path / "bin" / "tunnel-client"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    assert units.resolve_executable("tunnel-client", which=lambda n: str(link)) == link
    assert (
        units.resolve_executable("tunnel-client", which=lambda n: str(link)) != target
    )


def test_resolve_executable_refuses_what_it_cannot_run(tmp_path):
    with pytest.raises(
        units.UnitError, match="cannot resolve the binnacle-x executable"
    ):
        units.resolve_executable(
            "binnacle-x", argv0=str(tmp_path / "gone"), which=lambda n: None
        )
    plain = tmp_path / "plain"
    plain.write_text("not executable")
    with pytest.raises(units.UnitError):
        units.resolve_executable("binnacle-x", argv0=str(plain), which=lambda n: None)


# -- the process check --------------------------------------------------------


def exec_start(*argv: str) -> str:
    return (
        f"{{ path={argv[0]} ; argv[]={' '.join(argv)} ; ignore_errors=no ; "
        "start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }"
    )


def fake_show(props: dict[str, str]):
    def run(*args: str) -> subprocess.CompletedProcess:
        out = props.get(args[3], "") if args[0] == "show" else ""
        return subprocess.CompletedProcess(list(args), 0, stdout=out + "\n", stderr="")

    return run


HINTS = ("binnacle-x setup", "binnacle-x restart")


def test_exec_start_argv_parses_systemctl_show_output():
    line = exec_start("/v/bin/binnacle-x", "run")
    assert units.exec_start_argv(line) == ["/v/bin/binnacle-x", "run"]
    assert units.exec_start_argv("") == []
    assert units.exec_start_argv("{ path=/x ; ignore_errors=no }") == []


def test_proc_cmdline_reads_this_process():
    argv = units.proc_cmdline(os.getpid())
    assert argv and "python" in Path(argv[0]).name


def test_unit_process_ok_when_the_process_is_the_unit_command(tmp_path):
    exe = executable(tmp_path, "binnacle-x")
    run = fake_show({"ExecStart": exec_start(str(exe), "run"), "MainPID": "4242"})
    checks = units.check_unit_process(
        "x.service",
        "g",
        *HINTS,
        run=run,
        cmdline=lambda pid: ["/v/bin/python3", str(exe), "run"],
    )
    assert [c.status for c in checks] == ["ok"]
    assert checks[0].group == "g" and "pid 4242 is that command" in checks[0].detail


def test_unit_process_warns_when_the_process_predates_the_unit(tmp_path):
    exe = executable(tmp_path, "binnacle-x")
    run = fake_show({"ExecStart": exec_start(str(exe), "run"), "MainPID": "1196"})
    old = ["/v/bin/python3", "/v/bin/binnacle", "watchdog", "run"]
    checks = units.check_unit_process(
        "x.service", "g", *HINTS, run=run, cmdline=lambda pid: old
    )
    assert checks[0].status == "warn"
    assert "binnacle watchdog run" in checks[0].detail
    assert checks[0].hint == "binnacle-x restart"


def test_unit_process_fails_when_the_executable_is_missing(tmp_path):
    missing = tmp_path / "gone" / "binnacle-x"
    props = {"ExecStart": exec_start(str(missing), "run"), "MainPID": "0"}
    checks = units.check_unit_process("x.service", "g", *HINTS, run=fake_show(props))
    assert checks[0].status == "fail"
    assert "missing or not executable" in checks[0].detail
    assert checks[0].hint == "binnacle-x setup"


def test_unit_process_fails_without_exec_start():
    props = {
        "ExecStart": "",
        "LoadError": 'org.freedesktop.DBus.Error.FileNotFound "No such file"',
    }
    checks = units.check_unit_process("x.service", "g", *HINTS, run=fake_show(props))
    assert checks[0].status == "fail"
    assert "no ExecStart" in checks[0].detail and "No such file" in checks[0].detail


def test_unit_process_ok_when_the_unit_is_not_running(tmp_path):
    exe = executable(tmp_path, "binnacle-x")

    def no_pid(pid: int) -> list[str]:
        raise AssertionError("no pid to read")

    for main_pid in ("0", "", "n/a"):
        props = {"ExecStart": exec_start(str(exe), "run"), "MainPID": main_pid}
        checks = units.check_unit_process(
            "x.service", "g", *HINTS, run=fake_show(props), cmdline=no_pid
        )
        assert [c.status for c in checks] == ["ok"], main_pid


def test_unit_process_warns_when_the_cmdline_is_unreadable(tmp_path):
    exe = executable(tmp_path, "binnacle-x")
    props = {"ExecStart": exec_start(str(exe), "run"), "MainPID": "77"}

    def boom(pid: int) -> list[str]:
        raise OSError("gone")

    checks = units.check_unit_process(
        "x.service", "g", *HINTS, run=fake_show(props), cmdline=boom
    )
    assert checks[0].status == "warn" and "pid 77" in checks[0].detail


# -- the drift check ----------------------------------------------------------


def render_for(params) -> str:
    body = f"[Unit]\nDescription={params['name']}\n"
    return units.render(units.UnitSpec("x.service", "binnacle-x", body, params))


def test_unit_drift_ok_when_the_file_matches(tmp_path):
    path = tmp_path / "x.service"
    path.write_text(render_for({"name": "a"}))
    checks = units.check_unit_drift(
        path, "binnacle-x", render_for, "g", "binnacle-x setup"
    )
    assert [c.status for c in checks] == ["ok"]
    assert "matches `binnacle-x setup` (name=a)" in checks[0].detail


def test_unit_drift_warns_when_the_file_differs(tmp_path):
    path = tmp_path / "x.service"
    path.write_text(render_for({"name": "a"}).replace("Description=a", "Description=b"))
    checks = units.check_unit_drift(
        path, "binnacle-x", render_for, "g", "binnacle-x setup"
    )
    assert checks[0].status == "warn"
    assert "differs from what `binnacle-x setup` writes now" in checks[0].detail
    assert "first difference: -Description=b" in checks[0].detail
    assert checks[0].hint.startswith("binnacle-x setup, then restart")


def test_unit_drift_reports_missing_unmanaged_legacy_and_foreign(tmp_path):
    path = tmp_path / "x.service"
    args = ("binnacle-x", render_for, "g", "binnacle-x setup")
    assert units.check_unit_drift(path, *args)[0].status == "fail"
    path.write_text("[Unit]\nDescription=hand written\n")
    check = units.check_unit_drift(path, *args)[0]
    assert check.status == "warn" and "no marker" in check.detail
    assert "--dry-run" in check.hint and "--adopt" in check.hint
    path.write_text("# Managed by `binnacle setup`\n[Unit]\n")
    check = units.check_unit_drift(path, *args)[0]
    assert check.status == "warn" and "pre-2026-09-20 marker" in check.detail
    path.write_text(
        units.render(units.UnitSpec("x.service", "binnacle-y", "[Unit]\n", {}))
    )
    check = units.check_unit_drift(path, *args)[0]
    assert check.status == "warn" and "managed by `binnacle-y setup`" in check.detail


def test_unit_drift_warns_when_the_params_cannot_be_rendered(tmp_path):
    path = tmp_path / "x.service"
    path.write_text(
        units.render(
            units.UnitSpec("x.service", "binnacle-x", "[Unit]\n", {"other": "1"})
        )
    )
    check = units.check_unit_drift(
        path, "binnacle-x", render_for, "g", "binnacle-x setup"
    )[0]
    assert check.status == "warn" and "cannot be rendered" in check.detail

    def refuse(params) -> str:
        raise units.UnitError("no such mode")

    check = units.check_unit_drift(path, "binnacle-x", refuse, "g", "binnacle-x setup")[
        0
    ]
    assert check.status == "warn" and "no such mode" in check.detail


# -- the server unit ----------------------------------------------------------

DEV = {"mode": "dev", "host": "127.0.0.1", "port": "8000", "repo": "/home/me/binnacle"}
PROD = {
    "mode": "prod",
    "host": "127.0.0.1",
    "port": "8123",
    "binnacle": "/opt/bin/binnacle",
}


def test_server_unit_dev_mode_runs_the_checkout_with_reload():
    spec = server_unit.server_unit_spec(DEV)
    assert spec.name == "binnacle-mcp.service" and spec.owner == "binnacle"
    assert spec.params == DEV
    assert "WorkingDirectory=/home/me/binnacle\n" in spec.body
    assert (
        "ExecStart=/home/me/binnacle/.venv/bin/uvicorn binnacle.server:app "
        "--host 127.0.0.1 --port 8000 --reload --loop uvloop --http httptools\n"
    ) in spec.body
    assert "Restart=on-failure" in spec.body and "/dev/tcp/127.0.0.1/8000" in spec.body
    assert "development: checkout with auto-reload" in spec.body


def test_server_unit_prod_mode_runs_the_installed_serve():
    spec = server_unit.server_unit_spec(PROD)
    assert (
        "ExecStart=/opt/bin/binnacle serve --host 127.0.0.1 --port 8123\n" in spec.body
    )
    assert "WorkingDirectory" not in spec.body
    assert "Restart=always" in spec.body and "production" in spec.body


def test_server_unit_rejects_unknown_mode_and_missing_params():
    with pytest.raises(units.UnitError, match="unknown server mode"):
        server_unit.server_unit_spec({"mode": "staging"})
    with pytest.raises(KeyError):
        server_unit.server_unit_spec({"mode": "dev", "port": "8000"})
    with pytest.raises(KeyError):
        server_unit.server_unit_spec({"mode": "prod", "port": "8000"})


def test_render_server_unit_round_trips_through_the_marker():
    text = server_unit.render_server_unit(DEV)
    marker = units.read_marker(text)
    assert marker is not None and marker.owner == "binnacle" and marker.params == DEV
    assert server_unit.render_server_unit(marker.params) == text


def test_server_params_remember_the_checkout_and_resolve_the_executable(
    tmp_path, monkeypatch
):
    with pytest.raises(units.UnitError, match="needs the checkout"):
        server_unit.server_params("dev", None, "127.0.0.1", 8000)
    repo = tmp_path / "repo"
    assert server_unit.server_params("dev", repo, "127.0.0.1", 8000) == {
        "mode": "dev",
        "host": "127.0.0.1",
        "port": "8000",
        "repo": str(repo.resolve()),
    }
    exe = executable(tmp_path, "binnacle")
    monkeypatch.setattr(units, "resolve_executable", lambda name, **kw: exe)
    assert server_unit.server_params("prod", repo, "127.0.0.1", 8000) == {
        "mode": "prod",
        "host": "127.0.0.1",
        "port": "8000",
        "repo": str(repo.resolve()),
        "binnacle": str(exe),
    }
    assert "repo" not in server_unit.server_params("prod", None, "127.0.0.1", 8000)
