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
