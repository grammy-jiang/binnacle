"""Darwin doctor CLI dispatch, JSON schema and W3 gate contracts."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle import cli
from binnacle.diagnostics import darwin_doctor as native
from binnacle.diagnostics import doctor as linux_checks
from binnacle.doctor_contracts import fail, ok
from binnacle.platform import composition
from scripts.mac_w3_deploy_gate import parse_startup_doctor


def test_safe_darwin_aggregator_keeps_startup_when_other_checks_fail(monkeypatch):
    monkeypatch.setattr(
        linux_checks, "check_startup_imports", lambda: [ok("startup", "clean")]
    )
    monkeypatch.setattr(
        linux_checks, "check_provenance", lambda: [ok("version", "signed")]
    )
    monkeypatch.setattr(
        linux_checks,
        "check_config",
        lambda: (_ for _ in ()).throw(OSError("config private secret")),
    )
    monkeypatch.setattr(linux_checks, "check_config_keys", list)
    monkeypatch.setattr(linux_checks, "check_rg_version", lambda _rg: [])
    monkeypatch.setattr(linux_checks, "check_token", lambda path: [])
    monkeypatch.setattr(linux_checks, "check_endpoint", lambda url, path: [])
    monkeypatch.setattr(
        native, "check_launchd", lambda: ([ok("launchd", "healthy")], {"jobs": 1007})
    )
    monkeypatch.setattr(native, "check_native_job_manager", lambda revision, pids: [])
    monkeypatch.setattr(
        native,
        "runtime_provenance",
        lambda: SimpleNamespace(revision="a" * 12),
    )
    monkeypatch.setattr(native, "get_settings", lambda: SimpleNamespace(rg_bin="rg"))
    rows = native.run_all(server_url="http://127.0.0.1/mcp", token_file=Path("/none"))
    text, rc = linux_checks.render_json(rows)
    assert rc == 1
    body = json.loads(text)
    assert any(x["group"] == "startup" and x["status"] == "ok" for x in body["checks"])
    assert any(x["group"] == "config" and x["status"] == "fail" for x in body["checks"])
    assert "config private secret" not in text
    assert parse_startup_doctor(text)[:2] == (True, "startup_ok")


def test_startup_failure_keeps_w3_gate_blocked_in_json(monkeypatch):
    monkeypatch.setattr(
        linux_checks,
        "check_startup_imports",
        lambda: [fail("startup", "required module cannot load")],
    )
    monkeypatch.setattr(linux_checks, "check_provenance", list)
    monkeypatch.setattr(linux_checks, "check_config", list)
    monkeypatch.setattr(linux_checks, "check_config_keys", list)
    monkeypatch.setattr(linux_checks, "check_rg_version", lambda x: [])
    monkeypatch.setattr(linux_checks, "check_token", lambda _: [])
    monkeypatch.setattr(linux_checks, "check_endpoint", lambda x, y: [])
    monkeypatch.setattr(native, "check_launchd", lambda: ([], {}))
    monkeypatch.setattr(native, "check_native_job_manager", lambda rev, pids: [])
    monkeypatch.setattr(
        native, "runtime_provenance", lambda: SimpleNamespace(revision="a" * 12)
    )
    monkeypatch.setattr(native, "get_settings", lambda: SimpleNamespace(rg_bin="rg"))
    output, rc = linux_checks.render_json(
        native.run_all(server_url="http://localhost/mcp", token_file=Path("/none"))
    )
    assert rc == 1
    assert parse_startup_doctor(output)[:2] == (False, "startup_failure")


def test_darwin_cli_never_calls_linux_provisioner(monkeypatch, capsys):
    monkeypatch.setattr(composition, "host_os_family", lambda system=None: "darwin")
    monkeypatch.setattr(
        cli,
        "_provisioner",
        lambda: (_ for _ in ()).throw(AssertionError("Linux provisioner called")),
    )
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(serve=SimpleNamespace(host="127.0.0.1", port=8000)),
    )
    seen = []
    monkeypatch.setattr(
        native,
        "run_all",
        lambda *, server_url, token_file: (
            seen.append((server_url, token_file)) or [ok("startup", "clean")]
        ),
    )
    with pytest.raises(SystemExit) as done:
        cli.doctor(as_json=True)
    assert done.value.code == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["checks"][0]["group"] == "startup"
    assert seen == [("http://127.0.0.1:8000/mcp", cli.TOKEN_FILE)]


def test_linux_cli_uses_original_path_unchanged(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(composition, "host_os_family", lambda system=None: "linux")
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(
            serve=SimpleNamespace(host="127.0.0.1", port=8123),
            jobs=SimpleNamespace(socket_path=tmp_path / "jobs.sock"),
        ),
    )
    monkeypatch.setattr(
        cli,
        "_provisioner",
        lambda: SimpleNamespace(unit_path=lambda name: tmp_path / name),
    )
    seen = []
    monkeypatch.setattr(
        linux_checks,
        "run_all",
        lambda dep, *, since, probe: (
            seen.append((dep, since, probe)) or [ok("linux", "unchanged")]
        ),
    )
    with pytest.raises(SystemExit) as done:
        cli.doctor(as_json=True, since="-2 hours", probe=False)
    assert done.value.code == 0
    assert json.loads(capsys.readouterr().out)["checks"][0]["group"] == "linux"
    assert len(seen) == 1
    assert seen[0][0].jobs_unit == cli.JOBS_UNIT
    assert seen[0][1:] == ("-2 hours", False)


def test_launchd_probe_never_kickstarts_or_uses_shell(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "state = running\npid = 99\n", "")

    monkeypatch.setattr(native.subprocess, "run", fake_run)
    assert "pid = 99" in native._launchd_status("com.binnacle.mcp")
    assert calls[0][0] == ["/bin/launchctl", "print", "system/com.binnacle.mcp"]
    assert calls[0][1].get("check") is False
    assert calls[0][1].get("timeout") == 6
    assert not calls[0][1].get("shell")


@pytest.mark.parametrize("error", [OSError, subprocess.TimeoutExpired])
def test_launchd_probe_absence_is_unknown_not_a_success(monkeypatch, error):
    def bad(argv, **kw):
        if error is subprocess.TimeoutExpired:
            raise error(argv, 6)
        raise error("unavailable")

    monkeypatch.setattr(native.subprocess, "run", bad)
    assert native._launchd_status("com.binnacle.mcp") is None
