"""Coverage of doctor aggregation and low-level failure branches."""

import subprocess
from pathlib import Path

from binnacle import doctor
from binnacle import jobs as jobstore


def test_linger_enabled_handles_yes_no_and_command_failure(monkeypatch):
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="yes\n", stderr=""),
    )
    assert doctor.linger_enabled() is True

    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="no\n", stderr=""),
    )
    assert doctor.linger_enabled() is False

    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="", stderr="boom"),
    )
    assert doctor.linger_enabled() is None


def test_process_environ_returns_none_when_proc_entry_cannot_be_read(monkeypatch):
    monkeypatch.setattr(
        doctor.Path,
        "read_bytes",
        lambda self: (_ for _ in ()).throw(OSError("gone")),
    )

    assert doctor.process_environ(12345) is None


def test_check_config_reports_defaults_missing_root_and_load_failure(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    existing = tmp_path / "existing"
    existing.mkdir()
    missing = tmp_path / "missing"
    settings = SimpleNamespace(roots=SimpleNamespace(allowed=(existing, missing)))
    monkeypatch.setattr(doctor, "get_settings", lambda: settings)
    monkeypatch.setenv(doctor.CONFIG_FILE_ENV, str(tmp_path / "absent.toml"))

    checks = doctor.check_config()

    assert [c.status for c in checks] == ["ok", "ok", "warn"]
    assert "defaults" in checks[0].detail
    assert str(missing) in checks[-1].detail

    monkeypatch.setattr(
        doctor,
        "get_settings",
        lambda: (_ for _ in ()).throw(ValueError("bad config")),
    )
    (failed,) = doctor.check_config()
    assert failed.status == "fail"
    assert "bad config" in failed.detail


def test_boot_check_reports_runner_exception():
    def broken(*args, **kwargs):
        raise OSError("loginctl unavailable")

    (check,) = doctor.check_boot(broken, user="pi")

    assert check.status == "warn"
    assert "loginctl unavailable" in check.detail


def test_job_state_safe_hides_store_read_errors(monkeypatch):
    monkeypatch.setattr(
        jobstore,
        "job_state",
        lambda job_id: (_ for _ in ()).throw(KeyError(job_id)),
    )
    assert doctor._job_state_safe("gone") is None

    monkeypatch.setattr(
        jobstore,
        "job_state",
        lambda job_id: (_ for _ in ()).throw(OSError("disk")),
    )
    assert doctor._job_state_safe("gone") is None


def test_tunnel_log_file_handles_missing_bad_and_valid_configs(tmp_path):
    missing = tmp_path / "missing.json"
    assert doctor._tunnel_log_file(missing) is None

    bad = tmp_path / "bad.json"
    bad.write_text("{")
    assert doctor._tunnel_log_file(bad) is None

    scalar = tmp_path / "scalar.json"
    scalar.write_text('"not-a-dict"')
    assert doctor._tunnel_log_file(scalar) is None

    plain = tmp_path / "plain.json"
    plain.write_text("{}")
    assert doctor._tunnel_log_file(plain) is None

    valid = tmp_path / "valid.json"
    valid.write_text('{"log": {"file": "/tmp/tunnel.log"}}')
    assert doctor._tunnel_log_file(valid) == Path("/tmp/tunnel.log")


def test_run_all_composes_every_active_probe_check(tmp_path, monkeypatch):
    from types import SimpleNamespace

    dep = doctor.Deployment(
        server_unit="prod",
        tunnel_unit="tunnel",
        tunnel_config=tmp_path / "tunnel.json",
        token_file=tmp_path / "token",
        server_url="http://127.0.0.1:8000/mcp",
        user_bin=tmp_path / "bin",
        unit_path=tmp_path / "prod.service",
        render_unit=lambda params: "",
    )
    settings = SimpleNamespace(
        rg_bin="rg",
        jobs=SimpleNamespace(dir=tmp_path / "jobs"),
    )
    monkeypatch.setattr(doctor, "get_settings", lambda: settings)

    def mark(name):
        return lambda *a, **k: [doctor.ok(name, "ok")]

    monkeypatch.setattr(doctor, "check_config", mark("config"))
    monkeypatch.setattr(doctor, "check_token", mark("token"))
    monkeypatch.setattr(
        doctor,
        "check_units",
        lambda *a: ([doctor.ok("units", "ok")], "prod"),
    )
    monkeypatch.setattr(doctor.units, "check_unit_drift", mark("units"))
    monkeypatch.setattr(doctor.units, "check_unit_process", mark("units"))
    monkeypatch.setattr(doctor, "check_service_env", mark("service-env"))
    monkeypatch.setattr(doctor, "check_endpoint", mark("endpoint"))
    monkeypatch.setattr(doctor, "check_tunnel", mark("tunnel"))
    monkeypatch.setattr(doctor, "check_uplink", mark("uplink"))
    monkeypatch.setattr(doctor, "check_tunnel_poller", mark("poller"))
    monkeypatch.setattr(doctor, "check_boot", mark("boot"))
    monkeypatch.setattr(doctor, "check_jobs", mark("jobs"))
    monkeypatch.setattr(doctor, "check_journal", mark("journal"))
    monkeypatch.setattr(
        doctor,
        "_tunnel_log_file",
        lambda path: tmp_path / "tunnel.log",
    )

    checks = doctor.run_all(dep, since="-2 hours", probe=True)

    assert [c.group for c in checks] == [
        "config",
        "token",
        "units",
        "units",
        "units",
        "service-env",
        "endpoint",
        "tunnel",
        "uplink",
        "poller",
        "boot",
        "jobs",
        "journal",
    ]


def test_run_all_skips_optional_checks_when_inactive_and_local_only(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    dep = doctor.Deployment(
        server_unit="prod",
        tunnel_unit="tunnel",
        tunnel_config=tmp_path / "tunnel.json",
        token_file=tmp_path / "token",
        server_url="http://127.0.0.1:8000/mcp",
        user_bin=tmp_path / "bin",
    )
    monkeypatch.setattr(
        doctor,
        "get_settings",
        lambda: SimpleNamespace(
            rg_bin="rg",
            jobs=SimpleNamespace(dir=tmp_path / "jobs"),
        ),
    )
    monkeypatch.setattr(doctor, "check_config", list)
    monkeypatch.setattr(doctor, "check_token", lambda *a: [])
    monkeypatch.setattr(doctor, "check_units", lambda *a: ([], None))
    monkeypatch.setattr(doctor, "check_endpoint", lambda *a: [])
    monkeypatch.setattr(doctor, "check_tunnel", lambda *a, **k: [])
    monkeypatch.setattr(doctor, "check_boot", list)
    monkeypatch.setattr(doctor, "check_jobs", lambda *a: [])
    monkeypatch.setattr(doctor, "_tunnel_log_file", lambda path: None)
    monkeypatch.setattr(
        doctor,
        "check_uplink",
        lambda: (_ for _ in ()).throw(AssertionError("uplink called")),
    )
    monkeypatch.setattr(
        doctor,
        "check_journal",
        lambda *a: (_ for _ in ()).throw(AssertionError("journal called")),
    )

    assert doctor.run_all(dep, probe=False) == []
