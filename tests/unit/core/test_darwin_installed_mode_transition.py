"""Delayed launchd transitions and recovery tests."""

import pytest

from binnacle.deployment.darwin.installed_mode import TARGET, InstalledMcpModeError
from tests.unit.core.test_darwin_installed_mode import installed  # noqa: F401


def test_launchd_waits_for_delayed_label_absence(installed, monkeypatch):  # noqa: F811 - imported shared pytest fixture
    mode, runner, _, _ = installed
    runner.stale_after_bootout = 3
    monkeypatch.setattr(
        "binnacle.deployment.darwin.installed_mode.time.sleep", lambda _: None
    )
    assert "switched to dev" in mode.apply(mode.plan("dev"), force=True)
    assert runner.running


def test_exhausted_new_bootstrap_retries_restore_original(installed, monkeypatch):  # noqa: F811 - imported shared pytest fixture
    mode, runner, _, plist = installed
    old = plist.read_bytes()
    runner.transient_bootstrap_failures = 4
    monkeypatch.setattr(
        "binnacle.deployment.darwin.installed_mode.time.sleep", lambda _: None
    )
    with pytest.raises(InstalledMcpModeError, match="rollback attempted"):
        mode.apply(mode.plan("dev"), force=True)
    assert plist.read_bytes() == old and runner.running
    assert sum("bootstrap" in c for c in runner.calls) == 5


def test_bootstrap_partial_registration_is_rolled_back(installed, monkeypatch):  # noqa: F811 - imported shared pytest fixture
    mode, runner, _, plist = installed
    old = plist.read_bytes()
    runner.ambiguous_bootstrap_once = True
    monkeypatch.setattr(
        "binnacle.deployment.darwin.installed_mode.time.sleep", lambda _: None
    )
    with pytest.raises(InstalledMcpModeError, match="rollback attempted"):
        mode.apply(mode.plan("dev"), force=True)
    assert plist.read_bytes() == old and runner.running
    assert sum(c[-2:] == ("bootout", TARGET) for c in runner.calls) == 2
