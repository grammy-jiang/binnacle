"""Direct branch/fault tests for small watchdog companion components."""

import signal
import subprocess

from binnacle.ops.watchdog import command, diagnostics, lifecycle, maintenance, schedule
from binnacle.ops.watchdog.config import Policy
from binnacle.ops.watchdog.model import DeviceInfo, Preference, State
from binnacle.ops.watchdog.services import ServiceObservation, SystemObservation
from binnacle.uplink import ProbeResult, Route


def test_command_boundary_preserves_requested_argv_when_sudo_is_wrapped(monkeypatch):
    seen = {}

    monkeypatch.setattr(
        command.uplink,
        "sudo_timeout_argv",
        lambda args, timeout: ["sudo", "-n", "timeout", "2", "iw", "dev"],
    )

    def fake_run(argv, **kwargs):
        seen.update(argv=argv, kwargs=kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(command.subprocess, "run", fake_run)

    proc = command._run("sudo", "-n", "iw", "dev", timeout=2)

    assert seen["argv"][2] == "timeout"
    assert seen["kwargs"]["timeout"] == 7
    assert proc.args == ["sudo", "-n", "iw", "dev"]
    assert proc.stdout == "ok"


def test_command_boundary_converts_timeout_to_exit_124(monkeypatch):
    monkeypatch.setattr(
        command.uplink,
        "sudo_timeout_argv",
        lambda args, timeout: list(args),
    )
    monkeypatch.setattr(
        command.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(["nmcli"], 3)),
    )

    proc = command._run("nmcli", "device", timeout=3)

    assert proc.returncode == 124
    assert proc.args == ["nmcli", "device"]
    assert "timed out after 3 s" in proc.stderr


def test_diagnostics_describes_probe_usb_preference_and_extra_issues():
    state = State()
    state.usb_best_speed["wlan1"] = 5000
    state.extra_issues["host"] = "thermal"
    info = DeviceInfo(
        dev="wlan1",
        nm_state="disconnected",
        profile="slow",
        usb_speed=480,
    )
    probe = ProbeResult(
        dev="wlan1",
        layers={},
        errors={"probe": "permission denied"},
    )
    pref = Preference("wlan1", "slow", "fast", visible=False)

    issues = diagnostics.describe_issues(
        {"wlan1": info},
        {"wlan1": pref},
        {"wlan1": probe},
        state,
    )

    text = issues["wlan1"]
    assert "disconnected" in text
    assert "probes unavailable" in text
    assert "USB link 480" in text
    assert "fast preferred (not in range)" in text
    assert issues["host"] == "thermal"


def test_diagnostics_marks_resolver_degradation_without_overwriting_device_issue():
    state = State()
    state.extra_issues["wlan1"] = "older extra issue"
    probe = ProbeResult(
        dev="wlan1",
        layers={"gateway": True, "dns": False, "tcp": True},
        notes={"dns": "resolver"},
    )

    issues = diagnostics.describe_issues({}, {}, {"wlan1": probe}, state)

    assert "degraded" in issues["wlan1"]
    assert "DNS server problem" in issues["wlan1"]
    assert "older extra issue" not in issues["wlan1"]


def test_schedule_reload_episode_filter_and_first_ok():
    state = State()
    off = Policy(driver_reload_enabled=False)
    assert not schedule._reload_due(state, "wlan0", off, now=100)

    policy = Policy(driver_reload_enabled=True)
    state.last_reset["wlan0"] = 10
    state.last_reload["wlan0"] = 20
    assert schedule._reload_due(
        state,
        "wlan0",
        policy,
        now=100,
        first_ok=True,
        episode_start=50,
    )
    assert not schedule._reload_due(
        state,
        "wlan0",
        policy,
        now=100,
        first_ok=False,
        episode_start=50,
    )


def test_schedule_usb_speed_due_handles_first_and_repeated_attempts():
    state = State()
    policy = Policy(usb_speed_schedule=((0, 60.0),))
    assert schedule._usb_speed_due(state, "wlan1", policy, now=100)

    state.last_usb_speed_reset["wlan1"] = 80
    state.usb_speed_attempts["wlan1"] = 2
    assert not schedule._usb_speed_due(state, "wlan1", policy, now=100)
    assert schedule._usb_speed_due(state, "wlan1", policy, now=141)


def _cp(args, code=0):
    return subprocess.CompletedProcess(list(args), code, stdout="", stderr="boom")


def test_maintenance_applies_service_and_system_repairs(monkeypatch):
    policy = Policy(service_failures_before_action=3)
    state = State()
    obs = ServiceObservation(
        mcp_unit="mcp.service",
        endpoint_ok=False,
        tunnel_active=True,
        poll_failures=4,
        poll_failing_since=0.0,
        poll_last=0.0,
        tunnel_health_ok=False,
    )
    sys_obs = SystemObservation(
        nm_active=True,
        nm_responsive=False,
        supplicant_active=False,
    )
    monkeypatch.setattr(maintenance, "observe_services", lambda *a: obs)
    monkeypatch.setattr(
        maintenance,
        "evaluate_services",
        lambda *a: [(policy.tunnel_unit, "tunnel bad"), ("mcp.service", "mcp bad")],
    )
    tunnel_restarts = []
    monkeypatch.setattr(
        maintenance,
        "restart_tunnel",
        lambda *a: tunnel_restarts.append(a),
    )
    monkeypatch.setattr(maintenance, "tunnel_affinity_check", lambda *a: "wlan1")
    monkeypatch.setattr(maintenance, "nm_answers", lambda run: False)
    monkeypatch.setattr(maintenance, "observe_system", lambda *a: sys_obs)
    monkeypatch.setattr(
        maintenance,
        "evaluate_system",
        lambda *a: [(policy.nm_unit, "nm bad"), (policy.supplicant_unit, "supp bad")],
    )
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return _cp(args)

    note, tunnel = maintenance.maintain_services(
        state,
        policy,
        run,
        [Route("wlan1", "gw", "src", 100)],
        {"wlan1": ProbeResult("wlan1", layers={"tcp": True})},
        {"wlan1": DeviceInfo("wlan1", "connected")},
        cycle_n=4,
        now=1000.0,
        holding=False,
    )

    assert note == "mcp=DOWN,tunnel=FROZEN"
    assert tunnel == "wlan1"
    assert tunnel_restarts
    assert state.last_service_restart == {"tunnel": 1000.0, "mcp": 1000.0}
    assert state.last_system_restart == {"nm": 1000.0, "supplicant": 1000.0}
    assert "mcp" in state.extra_issues
    assert "tunnel" in state.extra_issues
    assert "networkmanager" in state.extra_issues
    assert "supplicant" in state.extra_issues
    assert any(call[0][:3] == ("systemctl", "--user", "restart") for call in calls)
    assert any(call[0][:4] == ("sudo", "-n", "systemctl", "restart") for call in calls)


def test_maintenance_holding_suppresses_repairs_and_reports_staleness(monkeypatch):
    policy = Policy(dry_run=True, tunnel_stale_after_s=10)
    state = State()
    obs = ServiceObservation(
        mcp_unit=None,
        endpoint_ok=None,
        tunnel_active=True,
        poll_failures=0,
        poll_last=10.0,
        tunnel_health_ok=True,
    )
    sys_obs = SystemObservation(
        nm_active=False,
        nm_responsive=False,
        supplicant_active=True,
    )
    monkeypatch.setattr(maintenance, "observe_services", lambda *a: obs)
    monkeypatch.setattr(
        maintenance,
        "evaluate_services",
        lambda *a: [("mcp.service", "would restart")],
    )
    monkeypatch.setattr(maintenance, "tunnel_affinity_check", lambda *a: "-")
    monkeypatch.setattr(maintenance, "nm_answers", lambda run: False)
    monkeypatch.setattr(maintenance, "observe_system", lambda *a: sys_obs)
    monkeypatch.setattr(
        maintenance,
        "evaluate_system",
        lambda *a: [(policy.nm_unit, "would restart")],
    )

    def forbidden(*args, **kwargs):
        raise AssertionError(f"restart attempted: {args}")

    note, tunnel = maintenance.maintain_services(
        state,
        policy,
        forbidden,
        [],
        {},
        {},
        cycle_n=5,
        now=100.0,
        holding=True,
    )

    assert note == "mcp=stopped,tunnel=ok"
    assert tunnel == "-"
    assert "silent for 90 s" in state.extra_issues["tunnel"]
    assert "networkmanager" in state.extra_issues
    assert state.last_service_restart == {}
    assert state.last_system_restart == {}


def test_maintenance_reports_low_poll_failure_without_offline_word(monkeypatch):
    policy = Policy(service_failures_before_action=3, system_service_repair=False)
    state = State()
    obs = ServiceObservation(
        tunnel_active=True,
        poll_failures=1,
        poll_last=100.0,
        tunnel_health_ok=True,
    )
    monkeypatch.setattr(maintenance, "observe_services", lambda *a: obs)
    monkeypatch.setattr(maintenance, "evaluate_services", lambda *a: [])
    monkeypatch.setattr(maintenance, "tunnel_affinity_check", lambda *a: "-")

    note, _ = maintenance.maintain_services(
        state,
        policy,
        lambda *a, **k: _cp(a),
        [],
        {},
        {},
        cycle_n=1,
        now=100.0,
        holding=False,
    )

    assert note == "mcp=stopped,tunnel=failing(1)"
    assert state.extra_issues["tunnel"] == "tunnel poll failing (1 in a row)"


class _FakeThread:
    def __init__(self, target=None, *, name="", **kwargs):
        self.target = target
        self.name = name
        self.alive = name == "watchdog-fast"

    def start(self):
        if self.name == "watchdog-cycle" and self.target is not None:
            self.target()

    def join(self, timeout=None):
        return None

    def is_alive(self):
        return self.alive


def test_lifecycle_starts_fast_path_and_stops_on_signal(monkeypatch, tmp_path):
    handlers = {}
    monkeypatch.setattr(lifecycle.threading, "Thread", _FakeThread)
    monkeypatch.setattr(
        lifecycle.signal,
        "signal",
        lambda sig, handler: handlers.setdefault(sig, handler),
    )
    monkeypatch.setattr(lifecycle, "versions", lambda run: {})
    monkeypatch.setattr(
        lifecycle,
        "supervise_fast_path",
        lambda state, policy, thread, start, exit_fn: (thread, False),
    )

    cycles = []

    def cycle_fn(*args, **kwargs):
        cycles.append(1)
        handlers[signal.SIGTERM](signal.SIGTERM, None)

    lifecycle.run_forever(
        tmp_path / "state.json",
        policy=Policy(fast_interval_s=5.0),
        run=lambda *a, **k: _cp(a),
        max_cycles=None,
        cycle_fn=cycle_fn,
        exit_fn=lambda code: (_ for _ in ()).throw(AssertionError(code)),
    )

    assert cycles == [1]
    assert signal.SIGTERM in handlers and signal.SIGINT in handlers


def test_lifecycle_tolerates_signal_install_failure_and_hung_fast_supervisor(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(lifecycle.threading, "Thread", _FakeThread)
    monkeypatch.setattr(
        lifecycle.signal,
        "signal",
        lambda *a: (_ for _ in ()).throw(ValueError("embedded")),
    )
    monkeypatch.setattr(lifecycle, "versions", lambda run: {})
    monkeypatch.setattr(
        lifecycle,
        "supervise_fast_path",
        lambda state, policy, thread, start, exit_fn: (thread, True),
    )

    lifecycle.run_forever(
        tmp_path / "state.json",
        policy=Policy(fast_interval_s=5.0),
        run=lambda *a, **k: _cp(a),
        max_cycles=None,
        cycle_fn=lambda *a, **k: None,
        exit_fn=lambda code: None,
    )
