"""Selection of the durable owner in managed vs ad-hoc deployments."""

from binnacle import jobs


def test_auto_owner_is_embedded_outside_managed_deployment(monkeypatch):
    monkeypatch.setattr(jobs, "_OWNER_SETTING", "auto")
    monkeypatch.delenv("BINNACLE_MANAGED_DEPLOYMENT", raising=False)
    assert jobs._resolve_owner_mode() == "embedded"


def test_auto_owner_uses_manager_in_setup_managed_deployment(monkeypatch):
    monkeypatch.setattr(jobs, "_OWNER_SETTING", "auto")
    monkeypatch.setenv("BINNACLE_MANAGED_DEPLOYMENT", "1")
    assert jobs._resolve_owner_mode() == "manager"


def test_explicit_owner_overrides_managed_marker(monkeypatch):
    monkeypatch.setattr(jobs, "_OWNER_SETTING", "embedded")
    monkeypatch.setenv("BINNACLE_MANAGED_DEPLOYMENT", "1")
    assert jobs._resolve_owner_mode() == "embedded"


def test_concurrent_stop_waits_for_durable_exit_record(monkeypatch):
    from binnacle import job_owner

    transient = {
        "state": "unknown",
        "exit_code": None,
        "signal": None,
    }
    settled = {
        "state": "exited",
        "exit_code": None,
        "signal": 15,
    }
    monkeypatch.setattr(jobs, "job_state", lambda job_id: transient)
    monkeypatch.setattr(jobs, "_read_meta", lambda job_id: {"stop_requested": True})
    monkeypatch.setattr(jobs, "await_exit", lambda job_id, timeout: settled)

    assert job_owner.stop_job("job") is settled
