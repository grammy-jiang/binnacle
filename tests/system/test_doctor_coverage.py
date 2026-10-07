"""Coverage of doctor aggregation and low-level failure branches."""

import pytest

from binnacle import doctor
from binnacle import jobs as jobstore


def test_linger_enabled_handles_yes_no_and_command_failure(monkeypatch):
    class Provisioner:
        enabled: bool | None = True

        def inspect_persistence(self):
            return type("Inspection", (), {"enabled": self.enabled})()

    provisioner = Provisioner()
    monkeypatch.setattr(doctor, "create_linux_provisioner", lambda: provisioner)

    assert doctor.linger_enabled() is True
    provisioner.enabled = False
    assert doctor.linger_enabled() is False
    provisioner.enabled = None
    assert doctor.linger_enabled() is None


def test_check_config_reports_defaults_missing_root_and_load_failure(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    existing = tmp_path / "existing"
    existing.mkdir()
    missing = tmp_path / "missing"
    settings = SimpleNamespace(roots=SimpleNamespace(allowed=(existing, missing)))
    monkeypatch.setattr(doctor, "get_settings", lambda: settings)
    monkeypatch.setattr(doctor, "create_service_inspector", lambda: object())
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


@pytest.mark.parametrize("probe", [False, True])
def test_run_all_composes_every_active_core_check(tmp_path, monkeypatch, probe):
    from types import SimpleNamespace

    dep = doctor.Deployment(
        server_unit="prod",
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

    expected = SimpleNamespace(package_version="1.0.0", revision="abc123def456")
    monkeypatch.setattr(doctor, "runtime_provenance", lambda: expected)
    monkeypatch.setattr(doctor, "check_provenance", mark("version"))
    monkeypatch.setattr(doctor, "check_config", mark("config"))
    monkeypatch.setattr(doctor, "check_token", mark("token"))
    monkeypatch.setattr(
        doctor,
        "check_units",
        lambda *a, **k: ([doctor.ok("units", "ok")], "prod"),
    )
    monkeypatch.setattr(doctor.units, "check_unit_drift", mark("units"))
    monkeypatch.setattr(doctor.units, "check_unit_process", mark("units"))
    monkeypatch.setattr(doctor, "check_service_env", mark("service-env"))
    monkeypatch.setattr(doctor, "check_endpoint", mark("endpoint"))
    monkeypatch.setattr(doctor, "check_boot", mark("boot"))
    monkeypatch.setattr(doctor, "check_jobs", mark("jobs"))
    monkeypatch.setattr(doctor, "check_journal", mark("journal"))

    checks = doctor.run_all(dep, since="-2 hours", probe=probe)

    assert [c.group for c in checks] == [
        "version",
        "config",
        "token",
        "units",
        "units",
        "units",
        "service-env",
        "endpoint",
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
    monkeypatch.setattr(doctor, "create_service_inspector", lambda: object())
    expected = SimpleNamespace(package_version="1.0.0", revision="abc123def456")
    monkeypatch.setattr(doctor, "runtime_provenance", lambda: expected)
    monkeypatch.setattr(doctor, "check_provenance", lambda value: [])
    monkeypatch.setattr(doctor, "check_config", list)
    monkeypatch.setattr(doctor, "check_token", lambda *a: [])
    monkeypatch.setattr(doctor, "check_units", lambda *a, **k: ([], None))
    monkeypatch.setattr(doctor, "check_endpoint", lambda *a: [])
    monkeypatch.setattr(doctor, "check_boot", list)
    monkeypatch.setattr(doctor, "check_jobs", lambda *a: [])
    monkeypatch.setattr(
        doctor,
        "check_journal",
        lambda *a: (_ for _ in ()).throw(AssertionError("journal called")),
    )

    assert doctor.run_all(dep, probe=False) == []
