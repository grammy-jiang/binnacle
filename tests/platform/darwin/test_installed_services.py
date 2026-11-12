"""Deploy-gate adapters for the installed Darwin LaunchDaemons, without launchd."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle.platform import composition
from binnacle.platform.contracts.service_log_contracts import ServiceLogError
from binnacle.platform.darwin import daemon_logstats
from binnacle.platform.darwin import service_launchd_system as system
from binnacle.platform.darwin.daemon_logstats import DarwinDaemonLogStatsSource

UNIT = "binnacle-mcp.service"
PRINT_RUNNING = (
    "system/com.binnacle.mcp = {\n"
    "\tstate = running\n"
    "\tprogram = /x/.venv/bin/binnacle\n"
    "\truns = 3\n"
    "\tpid = 4242\n"
    "\tendpoints = {\n"
    "\t\tstate = active\n"
    "\t}\n"
    "}\n"
)
PS = "    1     0   100\n 4242     1  2000\n 4243  4242   500\n 4244  4243    25\n 999 1 7\n"


def done(stdout: str = "", returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class Fake:
    """Answers launchctl/ps/sudo by argv; records every call."""

    def __init__(self, pids=(4242,), ps=PS, kick=None):
        self.pids, self.ps, self.kick, self.calls = list(pids), ps, kick, []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if argv[0] == "/bin/launchctl":
            pid = self.pids.pop(0) if len(self.pids) > 1 else self.pids[0]
            if pid is None:
                return done("", 113, "Could not find service")
            return done(PRINT_RUNNING.replace("4242", str(pid)))
        if argv[0] == "/bin/ps":
            return done("", 1) if self.ps is None else done(self.ps)
        if self.kick is not None:
            if isinstance(self.kick, BaseException):
                raise self.kick
            return self.kick
        return done()


@pytest.fixture
def fake(monkeypatch):
    runner = Fake()
    monkeypatch.setattr(system.subprocess, "run", runner)
    return runner


def test_unit_names_map_to_launchd_labels():
    assert system.launchd_label("binnacle-mcp.service") == "com.binnacle.mcp"
    assert system.launchd_label("binnacle-lsp-p4.service") == "com.binnacle.lsp-p4"
    for bad in (
        "binnacle-mcp",
        "other.service",
        "binnacle-.service",
        "binnacle-A.service",
    ):
        with pytest.raises(ValueError):
            system.launchd_label(bad)


def test_status_reads_only_top_level_launchd_facts(fake):
    status = system.LaunchdSystemServices().status(UNIT)
    assert (status.state, status.main_pid, status.restart_count) == ("active", 4242, 2)
    assert fake.calls[0][0] == ["/bin/launchctl", "print", "system/com.binnacle.mcp"]


@pytest.mark.parametrize(
    ("result", "state"),
    [
        (done("", 113, 'Could not find service "x"'), "inactive"),
        (done("", 5, "Bad request"), "unknown"),
        (done("system/x = {\n\tprogram = y\n}\n"), "unknown"),
        (done("system/x = {\n\tstate = not running\n}\n"), "inactive"),
        (None, "unknown"),
    ],
)
def test_status_absent_errors_and_stopped(monkeypatch, result, state):
    def run(argv, **kwargs):
        if result is None:
            raise subprocess.TimeoutExpired(argv, 10)
        return result

    monkeypatch.setattr(system.subprocess, "run", run)
    status = system.LaunchdSystemServices().status(UNIT)
    assert status.state == state
    assert status.main_pid is None


def test_rss_sums_the_main_process_tree(fake):
    assert system.LaunchdSystemServices().rss_kb(UNIT) == 2525.0


@pytest.mark.parametrize("ps", ["junk\n", " 4242 1 0\n"])
def test_rss_unknown_without_a_measured_main_process(monkeypatch, ps):
    monkeypatch.setattr(system.subprocess, "run", Fake(ps=ps))
    assert system.LaunchdSystemServices().rss_kb(UNIT) is None


def test_rss_and_start_unknown_when_stopped(monkeypatch):
    monkeypatch.setattr(system.subprocess, "run", Fake(pids=[None]))
    services = system.LaunchdSystemServices()
    assert services.rss_kb(UNIT) is None
    assert services.started_at_epoch(UNIT) is None


def test_rss_unknown_when_ps_fails(monkeypatch):
    monkeypatch.setattr(system.subprocess, "run", Fake(ps=None))
    assert system.LaunchdSystemServices().rss_kb(UNIT) is None


def test_start_time_comes_from_kinfo_proc_birth(fake, monkeypatch):
    seen = []

    def records(kind, pid):
        seen.append((kind, pid))
        return [SimpleNamespace(birth=(1_794_425_604, 19_822))]

    monkeypatch.setattr(system, "_process_records", records)
    started = system.LaunchdSystemServices().started_at_epoch(UNIT)
    assert started == pytest.approx(1_794_425_604.019822)
    assert seen == [(1, 4242)]


@pytest.mark.parametrize("answer", [OSError("no sysctl"), []])
def test_start_time_unknown_without_one_record(fake, monkeypatch, answer):
    def records(kind, pid):
        if isinstance(answer, BaseException):
            raise answer
        return answer

    monkeypatch.setattr(system, "_process_records", records)
    assert system.LaunchdSystemServices().started_at_epoch(UNIT) is None


def test_environment_facts_stay_unknown(fake):
    services = system.LaunchdSystemServices()
    assert services.main_process_has_environment(UNIT, "A", "b") is None
    assert services.main_process_path(UNIT) is None


def test_restart_kickstarts_with_sudo_and_waits_for_a_new_pid(monkeypatch):
    runner = Fake(pids=[4242, 4242, 5000])
    monkeypatch.setattr(system.subprocess, "run", runner)
    monkeypatch.setattr(system.time, "sleep", lambda _s: None)
    action = system.LaunchdSystemServices(poll_s=0).restart(UNIT, timeout=30)
    assert action.returncode == 0
    kick = [argv for argv, _ in runner.calls if argv[0] == "/usr/bin/sudo"]
    assert kick == [
        [
            "/usr/bin/sudo",
            "-n",
            "/bin/launchctl",
            "kickstart",
            "-k",
            "system/com.binnacle.mcp",
        ]
    ]


def test_restart_times_out_when_the_pid_never_changes(monkeypatch):
    monkeypatch.setattr(system.subprocess, "run", Fake(pids=[4242]))
    clock = iter([0.0, 0.0, 100.0])
    monkeypatch.setattr(system.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(system.time, "sleep", lambda _s: None)
    action = system.LaunchdSystemServices().restart(UNIT, timeout=5)
    assert (action.returncode, action.timed_out) == (124, True)
    assert "no new running process after 5 s" in action.stderr


@pytest.mark.parametrize(
    ("kick", "code", "timed_out"),
    [
        (done("", 1, "sudo: a password is required"), 1, False),
        (subprocess.TimeoutExpired(["sudo"], 90, b"o", b"e"), 124, True),
        (OSError("no sudo"), 127, False),
    ],
)
def test_restart_reports_kickstart_failures(monkeypatch, kick, code, timed_out):
    monkeypatch.setattr(system.subprocess, "run", Fake(kick=kick))
    action = system.LaunchdSystemServices().restart(UNIT)
    assert (action.returncode, action.timed_out) == (code, timed_out)
    assert action.stderr


def stamp(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000", time.localtime(epoch))


def write_log(root: Path, lines: list[str]) -> None:
    (root / "mcp.stderr.log").write_text("".join(f"{ln}\n" for ln in lines))
    (root / "mcp.stdout.log").write_text("INFO:     127.0.0.1 - GET /healthz 200\n")


def test_read_window_bisects_and_keeps_continuation_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon_logstats, "_BISECT_STOP", 256)
    base = 1_794_400_000.0
    lines = []
    for i in range(2000):
        lines.append(f"{stamp(base + i)} INFO: event=tool_call call=c{i}")
        lines.append(f"                    INFO     event=request_success n={i}")
    write_log(tmp_path, lines)
    text = DarwinDaemonLogStatsSource(root=tmp_path).read_window(
        (UNIT,), base + 1500, base + 1502
    )
    assert text.splitlines() == [
        f"{stamp(base + 1500)} INFO: event=tool_call call=c1500",
        "                    INFO     event=request_success n=1500",
        f"{stamp(base + 1501)} INFO: event=tool_call call=c1501",
        "                    INFO     event=request_success n=1501",
        f"{stamp(base + 1502)} INFO: event=tool_call call=c1502",
        "                    INFO     event=request_success n=1502",
    ]
    open_ended = DarwinDaemonLogStatsSource(root=tmp_path).read_window(
        ("com.binnacle.mcp",), base + 1999
    )
    assert open_ended.splitlines()[0].endswith("call=c1999")
    assert len(open_ended.splitlines()) == 2


def test_read_window_handles_unstamped_heads_and_long_gaps(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon_logstats, "_BISECT_STOP", 16)
    monkeypatch.setattr(daemon_logstats, "_SCAN_LINES", 2)
    base = 1_794_400_000.0
    write_log(
        tmp_path,
        [
            "orphan continuation",
            f"{stamp(base)} INFO: event=old",
            *["  wrapped"] * 5,
            f"{stamp(base + 100)} INFO: event=new",
        ],
    )
    source = DarwinDaemonLogStatsSource(root=tmp_path)
    assert source.read_window((UNIT,), base + 50).splitlines() == [
        f"{stamp(base + 100)} INFO: event=new"
    ]
    assert source.read_window((UNIT,), base + 200) == ""


def test_read_window_refuses_unknown_units_and_oversized_windows(tmp_path, monkeypatch):
    base = 1_794_400_000.0
    write_log(tmp_path, [f"{stamp(base)} INFO: event={'x' * 100}"])
    source = DarwinDaemonLogStatsSource(root=tmp_path)
    with pytest.raises(ServiceLogError, match="unrecognised"):
        source.read_window(("binnacle-lsp-p4.service",), base)
    monkeypatch.setattr(daemon_logstats, "WINDOW_MAX_BYTES", 10)
    with pytest.raises(ServiceLogError, match="too large"):
        source.read_window((UNIT,), base)


def test_installed_selection_on_darwin(monkeypatch):
    monkeypatch.setattr(composition.platform, "system", lambda: "Darwin")
    inspector = composition.create_service_inspector(installed=True)
    controller = composition.create_service_controller(installed=True)
    logs = composition.create_service_log_source(installed=True)
    assert isinstance(inspector, system.LaunchdSystemServices)
    assert isinstance(controller, system.LaunchdSystemServices)
    assert isinstance(logs, DarwinDaemonLogStatsSource)
    with pytest.raises(composition.UnsupportedHostOS):
        composition.create_service_inspector()
    with pytest.raises(composition.UnsupportedHostOS):
        composition.create_service_log_source()


def test_installed_selection_on_linux_is_the_systemd_user_unit(monkeypatch):
    from binnacle.platform.linux.service_journal import JournalServiceLogSource
    from binnacle.platform.linux.service_systemd import SystemdUserServices

    monkeypatch.setattr(composition.platform, "system", lambda: "Linux")
    assert isinstance(
        composition.create_service_controller(installed=True), SystemdUserServices
    )
    assert isinstance(
        composition.create_service_log_source(installed=True),
        JournalServiceLogSource,
    )
