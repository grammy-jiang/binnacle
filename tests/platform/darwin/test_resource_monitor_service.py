"""Darwin host metrics never control another process or alter any hardware."""

from __future__ import annotations

import logging
import plistlib
import subprocess
from pathlib import Path

import pytest

from binnacle.companions import resource_monitor_darwin as res

SAMPLE = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                       1234.
Pages active:                     9000.
Pages inactive:                   777.
Pages speculative:                5.
Pages wired down:                 500.
"""


def test_vm_stat_parses_only_named_quantities():
    metrics = res.parse_vm_stat(SAMPLE)
    assert metrics == {
        "vm_page_size_bytes": 16384,
        "vm_pages_free": 1234,
        "vm_pages_active": 9000,
        "vm_pages_inactive": 777,
        "vm_pages_speculative": 5,
        "vm_pages_wired": 500,
    }
    assert res.parse_vm_stat("unsupported or omitted page size") == {}
    assert res.parse_vm_stat(
        "Mach Virtual Memory Statistics: (page size of 4096 bytes)"
    ) == {"vm_page_size_bytes": 4096}


def test_snapshot_uses_only_native_read_commands_and_stdlib(tmp_path, monkeypatch):
    calls = []

    def read(argv):
        calls.append(argv)
        if argv[0] == "/usr/bin/vm_stat":
            return SAMPLE
        if argv[0] == "/usr/bin/memory_pressure":
            return "System-wide memory free percentage: 97%"
        if argv[0] == "/usr/sbin/sysctl":
            return "137438953472\n"
        raise AssertionError("unexpected command")

    monkeypatch.setattr(res, "_read_native", read)
    monkeypatch.setattr(res.os, "getloadavg", lambda: (1.234, 4, 9))
    monkeypatch.setattr(res.os, "cpu_count", lambda: 12)
    obj = res.snapshot(tmp_path)
    assert obj["load1"] == 1.23
    assert obj["load15"] == 9.0
    assert obj["cpu_count"] == 12
    assert obj["disk_total_bytes"] >= obj["disk_free_bytes"] > 0
    assert obj["vm_pages_inactive"] == 777
    assert obj["memory_pressure_free_percent"] == 97
    assert obj["memory_total_bytes"] == 137438953472
    assert calls == [
        ["/usr/bin/vm_stat"],
        ["/usr/bin/memory_pressure", "-Q"],
        ["/usr/sbin/sysctl", "-n", "hw.memsize"],
    ]


@pytest.mark.parametrize("value", ["not numeric", "-10", "0"])
def test_bad_memory_total_not_reported(monkeypatch, value):
    monkeypatch.setattr(
        res, "_read_native", lambda argv: value if "sysctl" in argv[0] else None
    )
    monkeypatch.setattr(res.os, "getloadavg", lambda: (0, 0, 0))
    monkeypatch.setattr(res.os, "cpu_count", lambda: 1)
    result = res.snapshot()
    assert "memory_total_bytes" not in result


@pytest.mark.parametrize("percentage", ["-5", "101", "bad"])
def test_invalid_memory_pressure_not_recorded(monkeypatch, percentage):
    monkeypatch.setattr(
        res,
        "_read_native",
        lambda argv: (
            f"System-wide memory free percentage: {percentage}%"
            if argv[0] == "/usr/bin/memory_pressure"
            else None
        ),
    )
    result = res.snapshot()
    assert "memory_pressure_free_percent" not in result


def test_snapshot_degrades_to_available_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(
        res.os, "getloadavg", lambda: (_ for _ in ()).throw(OSError("no load"))
    )
    monkeypatch.setattr(res.os, "cpu_count", lambda: None)
    monkeypatch.setattr(
        res.os, "statvfs", lambda path: (_ for _ in ()).throw(OSError("no disk"))
    )
    monkeypatch.setattr(res, "_read_native", lambda _: None)
    assert res.snapshot(tmp_path) == {}


@pytest.mark.parametrize("error", [OSError, subprocess.TimeoutExpired])
def test_subprocess_failure_is_unknown(monkeypatch, error):
    def run(*args, **kwargs):
        if error is subprocess.TimeoutExpired:
            raise error(args[0], 3)
        raise error("gone")

    monkeypatch.setattr(res.subprocess, "run", run)
    assert res._read_native(["/usr/bin/vm_stat"]) is None


def test_command_error_status_is_unknown(monkeypatch):
    monkeypatch.setattr(
        res.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, "ignored", "error"),
    )
    assert res._read_native(["/usr/bin/vm_stat"]) is None


def test_report_labels_and_unavailable_event(caplog):
    with caplog.at_level(logging.INFO, logger="binnacle.resource_monitor"):
        assert res.emit_snapshot(reader=lambda: {"cpu_count": 8, "load1": 1.5}) == {
            "cpu_count": 8,
            "load1": 1.5,
        }
        assert res.emit_snapshot(reader=dict) == {}
    assert "event=resource_snapshot host=darwin cpu_count=8 load1=1.5" in caplog.text
    assert "event=resource_snapshot_unavailable" in caplog.text


def test_plist_contains_no_commands_to_restart_or_modify_network(tmp_path):
    plist = plistlib.loads(
        res.render_launchd_plist(
            python=tmp_path / "venv/bin/python", home=tmp_path, username="user"
        )
    )
    assert plist["Label"] == "com.binnacle.resource-monitor"
    assert plist["UserName"] == "user"
    assert plist["Umask"] == 0o077
    assert plist["KeepAlive"] == {"SuccessfulExit": False}
    assert plist["ProgramArguments"] == [
        str(tmp_path / "venv/bin/python"),
        "-m",
        "binnacle.companions.resource_monitor_darwin",
        "--interval",
        "60",
    ]
    assert plist["StandardErrorPath"].endswith("/resource-monitor.stderr.log")
    assert not any("watchdog" in arg for arg in plist["ProgramArguments"])
    assert "Sockets" not in plist and "MachServices" not in plist


@pytest.mark.parametrize(
    "kwargs",
    [
        {"python": Path("relative"), "home": Path("/tmp"), "username": "user"},
        {"python": Path("/bin/python"), "home": Path("relative"), "username": "user"},
        {"python": Path("/bin/python"), "home": Path("/tmp"), "username": "bad;name"},
        {
            "python": Path("/bin/python"),
            "home": Path("/tmp"),
            "username": "ok",
            "group": "bad group",
        },
        {
            "python": Path("/bin/python"),
            "home": Path("/tmp"),
            "username": "ok",
            "interval_s": 5,
        },
        {
            "python": Path("/bin/python"),
            "home": Path("/tmp"),
            "username": "ok",
            "interval_s": 86400,
        },
    ],
)
def test_bad_plists_refused(kwargs):
    with pytest.raises(ValueError, match="invalid"):
        res.render_launchd_plist(**kwargs)


def test_single_snapshot_then_clean_exit(monkeypatch):
    from binnacle.companions import darwin_log_privacy

    monkeypatch.setattr(darwin_log_privacy, "harden_private_logs", lambda root: ())
    monkeypatch.setattr(res.platform, "system", lambda: "Darwin")
    from binnacle.companions import darwin_log_privacy

    monkeypatch.setattr(darwin_log_privacy, "logs_nearing_rotation", lambda root: ())
    calls = []
    monkeypatch.setattr(res, "emit_snapshot", lambda **kw: calls.append("one"))
    assert res.main(["--once"]) == 0
    assert calls == ["one"]


def test_loop_exits_only_on_interrupt(monkeypatch):
    from binnacle.companions import darwin_log_privacy

    monkeypatch.setattr(darwin_log_privacy, "harden_private_logs", lambda root: ())
    monkeypatch.setattr(res.platform, "system", lambda: "Darwin")
    from binnacle.companions import darwin_log_privacy

    monkeypatch.setattr(darwin_log_privacy, "logs_nearing_rotation", lambda root: ())
    monkeypatch.setattr(res, "emit_snapshot", lambda **kw: {})
    monkeypatch.setattr(
        res.time, "sleep", lambda s: (_ for _ in ()).throw(KeyboardInterrupt())
    )
    assert res.main(["--interval", "30"]) == 0


def test_platform_and_invalid_interval_fail_before_running(monkeypatch):
    monkeypatch.setattr(res.platform, "system", lambda: "Linux")
    with pytest.raises(SystemExit) as err:
        res.main(["--once"])
    assert err.value.code == 2
    monkeypatch.setattr(res.platform, "system", lambda: "Darwin")
    with pytest.raises(SystemExit) as err:
        res.main(["--interval", "1"])
    assert err.value.code == 2


def test_main_log_permission_fixup_and_refusal_are_logged(monkeypatch, caplog):
    from binnacle.companions import darwin_log_privacy

    monkeypatch.setattr(res.platform, "system", lambda: "Darwin")

    monkeypatch.setattr(darwin_log_privacy, "logs_nearing_rotation", lambda root: ())
    monkeypatch.setattr(res, "emit_snapshot", lambda **kw: {})
    seen = []
    monkeypatch.setattr(
        darwin_log_privacy,
        "harden_private_logs",
        lambda root: seen.append(root) or ("mcp.stderr.log",),
    )
    with caplog.at_level(logging.WARNING, logger="binnacle.resource_monitor"):
        assert res.main(["--once"]) == 0
    assert len(seen) == 1
    assert "event=resource_log_permissions_hardened count=1" in caplog.text

    def refuse(root):
        raise RuntimeError("unsafe")

    monkeypatch.setattr(darwin_log_privacy, "harden_private_logs", refuse)
    with caplog.at_level(logging.WARNING, logger="binnacle.resource_monitor"):
        assert res.main(["--once"]) == 0
    assert "event=resource_log_privacy_unverified" in caplog.text


def test_growth_alert_once_per_log_file(monkeypatch, caplog):
    from binnacle.companions import darwin_log_privacy

    monkeypatch.setattr(res.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(res, "emit_snapshot", lambda **kw: {})
    monkeypatch.setattr(darwin_log_privacy, "harden_private_logs", lambda root: ())
    monkeypatch.setattr(
        darwin_log_privacy,
        "logs_nearing_rotation",
        lambda root: (("mcp.stderr.log", 987654321),),
    )
    with caplog.at_level(logging.WARNING, logger="binnacle.resource_monitor"):
        assert res.main(["--once"]) == 0
    assert "event=resource_log_rotation_maintenance_needed" in caplog.text


def test_growth_audit_failure_never_prevents_resource_samples(monkeypatch, caplog):
    from binnacle.companions import darwin_log_privacy

    monkeypatch.setattr(res.platform, "system", lambda: "Darwin")
    samples = []
    monkeypatch.setattr(res, "emit_snapshot", lambda **kw: samples.append(1))
    monkeypatch.setattr(darwin_log_privacy, "harden_private_logs", lambda root: ())
    monkeypatch.setattr(
        darwin_log_privacy,
        "logs_nearing_rotation",
        lambda root: (_ for _ in ()).throw(RuntimeError("rotated")),
    )
    with caplog.at_level(logging.WARNING, logger="binnacle.resource_monitor"):
        assert res.main(["--once"]) == 0
    assert samples == [1]
    assert "event=resource_log_rotation_check_unavailable" in caplog.text


def test_low_disk_space_warns_at_linux_keep_free_equivalent(caplog):
    from binnacle.companions.darwin_log_privacy import MIN_DISK_FREE_BYTES

    with caplog.at_level(logging.WARNING, logger="binnacle.resource_monitor"):
        res.emit_snapshot(reader=lambda: {"disk_free_bytes": MIN_DISK_FREE_BYTES - 1})
    assert "event=resource_disk_space_low" in caplog.text
    assert f"keep_free_bytes={MIN_DISK_FREE_BYTES}" in caplog.text


def test_disk_free_healthy_or_missing_does_not_warn(caplog):
    from binnacle.companions.darwin_log_privacy import MIN_DISK_FREE_BYTES

    with caplog.at_level(logging.WARNING, logger="binnacle.resource_monitor"):
        res.emit_snapshot(reader=lambda: {"disk_free_bytes": MIN_DISK_FREE_BYTES})
        res.emit_snapshot(reader=lambda: {"cpu_count": 8})
    assert "event=resource_disk_space_low" not in caplog.text


def test_negative_disk_free_is_unknown_not_low_space(caplog):
    with caplog.at_level(logging.WARNING, logger="binnacle.resource_monitor"):
        res.emit_snapshot(reader=lambda: {"disk_free_bytes": -1})
    assert "event=resource_disk_space_low" not in caplog.text
