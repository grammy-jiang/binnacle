"""Opt-in watchdog maintenance fence cannot race a new restart action."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import pytest

from binnacle.companions import (
    service_watchdog as wd,
)
from binnacle.companions import (
    service_watchdog_maintenance as pause,
)
from binnacle.companions import (
    service_watchdog_safety as safety,
)
from tests.system.test_service_watchdog_maintenance import NONCE, arm


@pytest.fixture
def directory(tmp_path: Path) -> Path:
    root = tmp_path / "watchdog-maintenance"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    return root


def _watchdog(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    on_probe=None,
    on_restart=None,
) -> tuple[int, list[str]]:
    restarted: list[str] = []
    monkeypatch.setattr(
        wd.Watchdog,
        "cycle",
        lambda self, **kw: {"mcp": "restart_due", "tunnel": "restart_due"},
    )
    monkeypatch.setattr(
        wd.Watchdog,
        "observe",
        lambda self, service: wd.Observation(True, False),
    )
    if on_probe is None:
        on_probe = lambda **kwargs: (True, "verified")
    monkeypatch.setattr(safety, "recovery_allowed", on_probe)

    def restart(self, service):
        restarted.append(service)
        if on_restart:
            on_restart(service)
        return True

    monkeypatch.setattr(wd.Supervisor, "restart", restart)
    rc = wd.main(
        [
            "--once",
            "--restart-enabled",
            "--state-file",
            str(root.parent / "watchdog.json"),
            "--pause-file",
            str(root.parent / "legacy-absent.pause"),
            "--maintenance-pause-dir",
            str(root),
        ]
    )
    return rc, restarted


def test_opt_in_without_request_keeps_prior_watchdog_restart_semantics(
    directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rc, restarted = _watchdog(directory, monkeypatch)
    assert rc == 0
    assert restarted == ["mcp"]
    assert (directory / "restart.lock").stat().st_mode & 0o777 == 0o600


def test_acked_request_suppresses_every_watchdog_restart(
    directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arm(directory)
    rc, restarted = _watchdog(directory, monkeypatch)
    assert rc == 0
    assert restarted == []
    assert pause.confirmed_ack(directory, nonce=NONCE, watchdog_pid=os.getpid())
    assert not (directory.parent / "watchdog.json").exists()


def test_bad_request_fails_closed_and_emits_log_without_restart(
    directory: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    (directory / "request.json").write_text("corrupt!")
    (directory / "request.json").chmod(0o600)
    with caplog.at_level(logging.INFO, logger="binnacle.service_watchdog"):
        rc, restarted = _watchdog(directory, monkeypatch)
    assert rc == 0
    assert restarted == []
    assert "service_watchdog_maintenance_pause_unknown" in caplog.text
    assert not (directory / "ack.json").exists()


def test_missing_private_maintenance_directory_never_allows_restart(
    directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory.rmdir()
    rc, restarted = _watchdog(directory, monkeypatch)
    assert rc == 0
    assert restarted == []


def test_late_pause_arriving_after_observation_blocks_restart(
    directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = [0]

    def probe(**kwargs):
        seen[0] += 1
        if seen[0] == 1:
            with pause._directory(directory) as dfd, pause._interlock(dfd):
                arm(directory)
        return True, "verified"

    rc, restarted = _watchdog(directory, monkeypatch, on_probe=probe)
    assert rc == 0
    assert seen == [1]
    assert restarted == []
    assert pause.confirmed_ack(directory, nonce=NONCE, watchdog_pid=os.getpid())
    assert not (directory.parent / "watchdog.json").exists()


def test_watchdog_restart_holds_fence_for_entire_supervisor_action(
    directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    busy = [False]

    def restart(service):
        with (
            pytest.raises(pause.WatchdogPauseRefused, match="busy"),
            pause._directory(directory) as dfd,
            pause._interlock(dfd),
        ):
            pytest.fail("controller request would race restart")
        busy[0] = True

    rc, restarted = _watchdog(directory, monkeypatch, on_restart=restart)
    assert rc == 0
    assert restarted == ["mcp"]
    assert busy == [True]
    # The controller can only arm after the restart action releases the lock.
    with pause._directory(directory) as dfd, pause._interlock(dfd):
        arm(directory)
    assert pause.WatchdogMaintenanceFence(directory).poll()


def test_future_controller_cannot_claim_old_ack_when_nonce_changes(
    directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arm(directory)
    assert _watchdog(directory, monkeypatch)[1] == []
    request = directory / "request.json"
    request.write_text(
        json.dumps(
            {"version": 1, "nonce": "b" * 32, "scope": "all", "until": time.time() + 80}
        )
    )
    request.chmod(0o600)
    assert not pause.confirmed_ack(directory, nonce="b" * 32, watchdog_pid=os.getpid())
    assert pause.WatchdogMaintenanceFence(directory).poll()
    assert pause.confirmed_ack(directory, nonce="b" * 32, watchdog_pid=os.getpid())
