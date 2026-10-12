"""Conservative MCP/tunnel watchdog: application only, fail-closed recovery."""

from __future__ import annotations

import logging
import os
from types import SimpleNamespace

import pytest

from binnacle.companions import service_watchdog as wd


class FakeSupervisor:
    host = "darwin"

    def __init__(self, services=None):
        self.services = services or {"mcp": True, "tunnel": True}
        self.restarted = []

    def running(self, service):
        return self.services[service]

    def restart(self, service):
        self.restarted.append(service)
        return True


def quick(**overrides):
    return wd.Policy(
        **(
            {
                "interval_s": 10,
                "consecutive_failures": 3,
                "startup_grace_s": 20,
                "wake_gap_s": 60,
                "restart_cooldown_s": 90,
                "probe_timeout_s": 1,
            }
            | overrides
        )
    )


def test_failure_streak_only_restarts_unresponsive_running_services():
    supervisor = FakeSupervisor()
    watcher = wd.Watchdog(supervisor, policy=quick(), restart_enabled=True)
    watcher.observe = lambda s: wd.Observation(True, s != "mcp")
    first = watcher.cycle(now_mono=100, now_wall=1000)
    second = watcher.cycle(now_mono=110, now_wall=1010)
    third = watcher.cycle(now_mono=120, now_wall=1020)
    assert first == {"mcp": "observe", "tunnel": "observe"}
    assert second == first
    assert third == {"mcp": "restart_due", "tunnel": "observe"}
    assert supervisor.restarted == []  # the engine never bypasses durable gate


@pytest.mark.parametrize(
    "state,responds",
    [
        (None, None),
        (False, None),
        (True, None),
        (True, True),
    ],
)
def test_missing_ambiguous_or_stopped_services_never_restart(state, responds):
    watcher = wd.Watchdog(FakeSupervisor(), policy=quick(), restart_enabled=True)
    watcher.observe = lambda s: wd.Observation(state, responds)
    for t in range(10):
        assert watcher.cycle(now_mono=10 + t * 10, now_wall=1000 + t * 10) == {
            "mcp": "observe",
            "tunnel": "observe",
        }


def test_wake_gap_clears_streak_and_restarts_grace_window():
    watcher = wd.Watchdog(FakeSupervisor(), policy=quick(), restart_enabled=True)
    watcher.observe = lambda s: wd.Observation(True, False)
    for t in (100, 110):
        watcher.cycle(now_mono=t, now_wall=t + 900)
    assert watcher.cycle(now_mono=300, now_wall=1200) == {
        "mcp": "observe",
        "tunnel": "observe",
    }
    assert watcher.cycle(now_mono=310, now_wall=1210) == {
        "mcp": "observe",
        "tunnel": "observe",
    }
    assert watcher.cycle(now_mono=320, now_wall=1220) == {
        "mcp": "restart_due",
        "tunnel": "restart_due",
    }


def test_cooldown_and_dry_run_enforced():
    watcher = wd.Watchdog(
        FakeSupervisor(),
        policy=quick(),
        state=wd.WatchState(last_attempt={"mcp": 1050}),
        restart_enabled=False,
    )
    watcher.observe = lambda s: wd.Observation(True, False)
    for t in (100, 110):
        watcher.cycle(now_mono=t, now_wall=1000 + t - 100)
    result = watcher.cycle(now_mono=120, now_wall=1100)
    assert result == {"mcp": "cooldown", "tunnel": "dry_run"}


def test_supervisor_mappings_never_allow_jobs_or_network_restarts(monkeypatch):
    instance = wd.Supervisor("darwin")
    invoked = []

    def fake_run(args):
        invoked.append(args)
        return SimpleNamespace(returncode=0, stdout="state = running\n", stderr="")

    monkeypatch.setattr(instance, "_run", fake_run)
    assert instance.running("mcp") is True
    assert instance.restart("tunnel") is True
    assert invoked == [
        ["/bin/launchctl", "print", "system/com.binnacle.mcp"],
        [
            "sudo",
            "-n",
            "/bin/launchctl",
            "kickstart",
            "-k",
            "system/com.binnacle.tunnel",
        ],
    ]
    with pytest.raises(KeyError):
        instance.restart("jobs")
    with pytest.raises(KeyError):
        instance.restart("NetworkManager.service")
    instance = wd.Supervisor("linux")
    monkeypatch.setattr(instance, "_run", fake_run)
    assert instance.restart("mcp") is True
    assert invoked[-1] == ["systemctl", "--user", "restart", "binnacle-mcp.service"]


def test_loopback_health_url_guard(tmp_path):
    f = tmp_path / "health.url"
    f.write_text("http://127.0.0.1:23456\n")
    assert wd._read_tunnel_health_url(f) == "http://127.0.0.1:23456/api/status"
    for url in (
        "https://127.0.0.1:23456",
        "http://api.openai.com:443",
        "file:///etc/passwd",
        "http://127.0.0.1:2@evil.example:99",
        "http://[::2]:8080",
    ):
        f.write_text(url)
        assert wd._read_tunnel_health_url(f) is None
    f.unlink()
    f.symlink_to(tmp_path / "external")
    assert wd._read_tunnel_health_url(f) is None


def test_persistent_cooldown_and_corruption_fail_closed(tmp_path):
    path = tmp_path / "state" / "watchdog.json"
    wd._persist_attempts(path, {"mcp": 1000.0})
    assert wd._load_attempts(path) == {"mcp": 1000.0}
    assert os.stat(path).st_mode & 0o077 == 0
    path.write_text('{"version":1, "attempts": {"mcp": "bad"}}')
    with pytest.raises(RuntimeError, match="fail closed"):
        wd._load_attempts(path)
    path.write_text('{"version":1, "attempts": {"usb_reset": 1000}}')
    with pytest.raises(RuntimeError, match="fail closed"):
        wd._load_attempts(path)
    path.write_text('{"version":1, "attempts": {"mcp": true}}')
    with pytest.raises(RuntimeError, match="fail closed"):
        wd._load_attempts(path)


@pytest.mark.parametrize(
    "invalid",
    [
        {"interval_s": 0},
        {"consecutive_failures": 1},
        {"restart_cooldown_s": 0},
        {"wake_gap_s": 29},
    ],
)
def test_bad_policy_is_rejected(invalid):
    with pytest.raises(ValueError):
        wd.Policy(**invalid)


def test_live_once_is_observation_only(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(wd.Supervisor, "running", lambda self, service: False)
    with caplog.at_level(logging.INFO):
        result = wd.main(
            [
                "--once",
                "--state-file",
                str(tmp_path / "fresh" / "wd.json"),
                "--health-file",
                str(tmp_path / "missing.url"),
            ]
        )
    assert result == 0
    assert not (tmp_path / "fresh" / "wd.json").exists()
    assert any("event=service_watchdog_check" in r.message for r in caplog.records)


def test_paused_recovery_never_invokes_restart(tmp_path, monkeypatch):
    pause = tmp_path / "paused"
    pause.touch()
    invoked = []
    monkeypatch.setattr(
        wd.Watchdog,
        "cycle",
        lambda self, **kw: {"mcp": "restart_due", "tunnel": "restart_due"},
    )
    monkeypatch.setattr(
        wd.Supervisor, "restart", lambda self, service: invoked.append(service)
    )
    assert (
        wd.main(
            [
                "--once",
                "--restart-enabled",
                "--pause-file",
                str(pause),
                "--state-file",
                str(tmp_path / "state.json"),
            ]
        )
        == 0
    )
    assert invoked == []
    assert not (tmp_path / "state.json").exists()


def test_max_one_recovery_action_per_cycle(tmp_path, monkeypatch):
    invoked = []
    monkeypatch.setattr(
        wd.Watchdog,
        "cycle",
        lambda self, **kw: {"mcp": "restart_due", "tunnel": "restart_due"},
    )
    monkeypatch.setattr(
        wd.Supervisor,
        "restart",
        lambda self, service: invoked.append(service) or True,
    )
    assert (
        wd.main(
            [
                "--once",
                "--restart-enabled",
                "--pause-file",
                str(tmp_path / "absent.pause"),
                "--state-file",
                str(tmp_path / "state.json"),
            ]
        )
        == 0
    )
    assert invoked == ["mcp"]
    assert wd._load_attempts(tmp_path / "state.json").keys() == {"mcp"}


def test_os_specific_tunnel_health_locations(monkeypatch, tmp_path):
    monkeypatch.setattr(wd.Path, "home", lambda: tmp_path)
    assert wd._default_health_file("darwin") == (
        tmp_path / ".config/tunnel-client/binnacle-mac-health.url"
    )
    assert wd._default_health_file("linux") == (
        tmp_path / ".local/state/tunnel-client/health/binnacle.url"
    )
