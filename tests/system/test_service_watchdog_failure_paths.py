"""Negative-path and crash-safety coverage for the application-only watchdog.

All process/HTTP/recovery actions are fakes. No test contacts a live service.
"""

from __future__ import annotations

import logging
import subprocess
from types import SimpleNamespace

import pytest

from binnacle.companions import service_watchdog as wd


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://127.0.0.1:12", "http://127.0.0.1:12/api/status"),
        ("http://[::1]:12000", "http://[::1]:12000/api/status"),
        ("http://127.0.0.1:notaport", None),
        ("http://127.0.0.1", None),
        ("http://me:password@127.0.0.1:12", None),
        ("http://192.168.1.1:10", None),
    ],
)
def test_healthfile_url_validation(tmp_path, url, expected):
    file = tmp_path / "url"
    file.write_text(url)
    assert wd._read_tunnel_health_url(file) == expected


def test_healthfile_oversize_invalid_utf8_and_no_owner(tmp_path, monkeypatch):
    file = tmp_path / "url"
    file.write_text("z" * 300)
    assert wd._read_tunnel_health_url(file) is None
    file.write_bytes(b"\xff")
    assert wd._read_tunnel_health_url(file) is None
    file.write_text("http://127.0.0.1:1234")
    monkeypatch.setattr(wd.os, "getuid", lambda: -99999)
    assert wd._read_tunnel_health_url(file) is None


def test_healthfile_fd_closed_when_read_setup_fails(tmp_path, monkeypatch):
    file = tmp_path / "url"
    file.write_text("http://127.0.0.1:11234")
    original_open = wd.os.open
    original_close = wd.os.close
    opened = []
    closed = []

    def open_file(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        opened.append(fd)
        return fd

    def close_file(fd):
        closed.append(fd)
        return original_close(fd)

    monkeypatch.setattr(wd.os, "open", open_file)
    monkeypatch.setattr(wd.os, "close", close_file)
    monkeypatch.setattr(
        wd.os, "fdopen", lambda *_: (_ for _ in ()).throw(OSError("denied"))
    )
    assert wd._read_tunnel_health_url(file) is None
    assert opened == closed


@pytest.mark.parametrize(
    ("url", "status", "expected"),
    [
        ("https://127.0.0.1:12", 200, None),
        ("http://localhost:12", 200, None),
        ("http://127.0.0.1:abc", 200, None),
        ("http://127.0.0.1", 200, None),
        ("http://127.0.0.1:12233/", 204, True),
        ("http://127.0.0.1:12233/healthz", 503, None),
    ],
)
def test_local_http_only_and_server_error_ambiguous(monkeypatch, url, status, expected):
    calls = []

    class Connection:
        def __init__(self, *args, **kwargs):
            calls.append(("init", args, kwargs))

        def request(self, *args, **kwargs):
            calls.append(("request", args, kwargs))

        def getresponse(self):
            return SimpleNamespace(status=status)

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(wd.http.client, "HTTPConnection", Connection)
    assert wd._local_http_responds(url, 1.2) is expected
    if expected is not None:
        assert calls[-1] == ("close",)


@pytest.mark.parametrize("error", [OSError, wd.http.client.HTTPException, TimeoutError])
def test_local_http_connection_failures_are_recorded_as_down(monkeypatch, error):
    calls = []

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            raise error("simulated failure")

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(wd.http.client, "HTTPConnection", Connection)
    assert wd._local_http_responds("http://127.0.0.1:20/healthz", 0.1) is False
    assert calls == ["closed"]


@pytest.mark.parametrize(
    ("host", "value", "expected"),
    [
        ("linux", "active\n", True),
        ("linux", "inactive\n", False),
        ("linux", "failed\n", False),
        ("linux", "activating\n", False),
        ("linux", "unknown\n", None),
        ("darwin", "state = running\n", True),
        ("darwin", "state = waiting\n", False),
        ("darwin", "state = stopped\n", False),
        ("darwin", "state = weird\n", None),
    ],
)
def test_supervisor_all_service_states(monkeypatch, host, value, expected):
    sup = wd.Supervisor(host)
    monkeypatch.setattr(
        sup,
        "_run",
        lambda argv: subprocess.CompletedProcess(argv, 0, value, ""),
    )
    assert sup.running("mcp") is expected


def test_supervisor_unavailable_and_nonzero_launchctl(monkeypatch):
    with pytest.raises(ValueError, match="host family"):
        wd.Supervisor("windows")
    for host in ("linux", "darwin"):
        sup = wd.Supervisor(host)
        monkeypatch.setattr(sup, "_run", lambda _: None)
        assert sup.running("mcp") is None
        assert sup.restart("mcp") is False
    mac = wd.Supervisor("darwin")
    monkeypatch.setattr(
        mac,
        "_run",
        lambda args: subprocess.CompletedProcess(args, 1, "state = running\n", ""),
    )
    assert mac.running("tunnel") is None
    assert mac.restart("tunnel") is False


@pytest.mark.parametrize("error", [OSError, subprocess.TimeoutExpired])
def test_supervisor_command_errors_fail_unknown(monkeypatch, error):
    def run(*args, **kwargs):
        if error is subprocess.TimeoutExpired:
            raise error(args[0], 10)
        raise error("missing")

    monkeypatch.setattr(wd.subprocess, "run", run)
    sup = wd.Supervisor("linux")
    assert sup.running("mcp") is None
    assert sup.restart("mcp") is False


def test_supervisor_observe_urls_without_network(tmp_path, monkeypatch):
    sup = wd.Supervisor("linux")
    monkeypatch.setattr(sup, "running", lambda service: True)
    seen = []
    monkeypatch.setattr(
        wd,
        "_local_http_responds",
        lambda url, timeout: seen.append((url, timeout)) or True,
    )
    path = tmp_path / "url"
    path.write_text("http://127.0.0.1:4567")
    watcher = wd.Watchdog(sup, health_file=path)
    assert watcher.observe("mcp") == wd.Observation(True, True)
    assert watcher.observe("tunnel") == wd.Observation(True, True)
    assert seen[0][0] == "http://127.0.0.1:8000/healthz"
    assert seen[1][0] == "http://127.0.0.1:4567/api/status"
    watcher.health_file = None
    assert watcher.observe("tunnel") == wd.Observation(True, None)
    monkeypatch.setattr(sup, "running", lambda service: False)
    assert watcher.observe("mcp") == wd.Observation(False, None)


def test_startup_grace_prevents_restart_during_validated_failures():
    sup = wd.Supervisor("linux")
    w = wd.Watchdog(
        sup,
        policy=wd.Policy(
            interval_s=10,
            consecutive_failures=2,
            startup_grace_s=100,
            wake_gap_s=110,
            restart_cooldown_s=100,
        ),
        restart_enabled=True,
    )
    w.observe = lambda _: wd.Observation(True, False)
    assert w.cycle(now_mono=10, now_wall=1000)["mcp"] == "observe"
    assert w.cycle(now_mono=20, now_wall=1010)["mcp"] == "startup_grace"


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        '{"version":2,"attempts":{}}',
        '{"version":1,"attempts":[]}',
        '{"version":1,"attempts":{"mcp":-1}}',
        '{"version":1,"attempts":{"mcp":100000000000000}}',
    ],
)
def test_persisted_recovery_state_corruption_is_fail_closed(tmp_path, payload):
    file = tmp_path / "state.json"
    file.write_text(payload)
    with pytest.raises(RuntimeError, match="fail closed"):
        wd._load_attempts(file)


def test_recovery_state_oversize_and_symlink_refusal(tmp_path):
    file = tmp_path / "state.json"
    file.write_bytes(b"x" * 4100)
    with pytest.raises(RuntimeError, match="fail closed"):
        wd._load_attempts(file)
    safe = tmp_path / "safe"
    safe.write_text('{"version":1,"attempts":{}}')
    file.unlink()
    file.symlink_to(safe)
    with pytest.raises(RuntimeError, match="fail closed"):
        wd._load_attempts(file)


def test_persisted_recovery_state_atomic_replace_failure_cleans_temp(
    tmp_path, monkeypatch
):
    file = tmp_path / "new" / "state.json"

    def failed_replace(src, dst):
        raise OSError("simulated fsync/rename failure")

    monkeypatch.setattr(wd.os, "replace", failed_replace)
    with pytest.raises(OSError):
        wd._persist_attempts(file, {"mcp": 1234.0})
    assert not file.exists()
    assert list(file.parent.glob("*.tmp")) == []


def test_main_rejects_invalid_policy_without_starting(tmp_path):
    assert (
        wd.main(
            [
                "--once",
                "--interval",
                "0",
                "--state-file",
                str(tmp_path / "state.json"),
            ]
        )
        == 2
    )


def test_main_refuses_second_instance_lock(tmp_path, monkeypatch):
    def locked(*args):
        raise BlockingIOError("another watchdog owns this lock")

    real_close = wd.os.close
    closed = []

    def close(fd):
        closed.append(fd)
        real_close(fd)

    monkeypatch.setattr(wd.fcntl, "flock", locked)
    monkeypatch.setattr(wd.os, "close", close)
    assert wd.main(["--once", "--state-file", str(tmp_path / "state.json")]) == 2
    assert len(closed) == 1  # even a failed lock must close its descriptor


def test_main_refuses_corrupt_state(tmp_path):
    file = tmp_path / "state.json"
    file.write_text("corrupt")
    assert wd.main(["--once", "--state-file", str(file)]) == 2


def test_main_restart_persistence_failure_never_calls_supervisor(
    tmp_path, monkeypatch, caplog
):
    from binnacle.companions import service_watchdog_safety

    monkeypatch.setattr(
        service_watchdog_safety,
        "recovery_allowed",
        lambda **kwargs: (True, "verified"),
    )
    called = []
    monkeypatch.setattr(wd.Watchdog, "cycle", lambda self, **kw: {"mcp": "restart_due"})
    monkeypatch.setattr(
        wd.Supervisor,
        "restart",
        lambda self, service: called.append(service) or True,
    )
    monkeypatch.setattr(
        wd,
        "_persist_attempts",
        lambda *_: (_ for _ in ()).throw(OSError("read-only device")),
    )
    with caplog.at_level(logging.ERROR, logger="binnacle.service_watchdog"):
        assert (
            wd.main(
                [
                    "--once",
                    "--restart-enabled",
                    "--state-file",
                    str(tmp_path / "state.json"),
                    "--pause-file",
                    str(tmp_path / "absent"),
                ]
            )
            == 0
        )
    assert called == []
    assert "event=service_watchdog_recovery_blocked" in caplog.text


def test_main_ctrl_c_completes_without_orphan_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(wd.Watchdog, "cycle", lambda self, **kw: {"mcp": "observe"})
    monkeypatch.setattr(
        wd.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    assert (
        wd.main(
            [
                "--state-file",
                str(tmp_path / "state.json"),
                "--pause-file",
                str(tmp_path / "missing"),
            ]
        )
        == 0
    )
