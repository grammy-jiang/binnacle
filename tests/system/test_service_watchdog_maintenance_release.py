"""Fenced pause release tests: only owner nonce, no service or log operations."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from binnacle.companions import service_watchdog_maintenance as pause
from tests.system.test_service_watchdog_maintenance import NONCE, arm


@pytest.fixture
def root(tmp_path: Path) -> Path:
    directory = tmp_path / "watchdog"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    return directory


def test_release_clears_matching_request_and_ack_only(root: Path) -> None:
    pause.request_pause(root, nonce=NONCE, until=time.time() + 80)
    assert pause.WatchdogMaintenanceFence(root).poll()
    assert pause.confirmed_ack(
        root, nonce=NONCE, watchdog_pid=__import__("os").getpid()
    )
    pause.release_pause(root, nonce=NONCE)
    assert not (root / "request.json").exists()
    assert not (root / "ack.json").exists()
    assert not pause.WatchdogMaintenanceFence(root).poll()
    with pause.WatchdogMaintenanceFence(root).action() as can:
        assert can


def test_release_before_ack_still_clears_own_request(root: Path) -> None:
    pause.request_pause(root, nonce=NONCE, until=time.time() + 70)
    assert not (root / "ack.json").exists()
    pause.release_pause(root, nonce=NONCE)
    assert not (root / "request.json").exists()
    assert not (root / "ack.json").exists()


@pytest.mark.parametrize("nonce", ["wrong", "b" * 32])
def test_foreign_release_nonce_does_not_remove_anything(root: Path, nonce: str) -> None:
    arm(root)
    pause.WatchdogMaintenanceFence(root).poll()
    req = (root / "request.json").read_bytes()
    ack = (root / "ack.json").read_bytes()
    with pytest.raises(pause.WatchdogPauseRefused, match="nonce|untrusted"):
        pause.release_pause(root, nonce=nonce)
    assert (root / "request.json").read_bytes() == req
    assert (root / "ack.json").read_bytes() == ack


def test_release_without_request_is_always_refused(root: Path) -> None:
    with pytest.raises(pause.WatchdogPauseRefused, match="untrusted"):
        pause.release_pause(root, nonce=NONCE)


def test_unknown_ack_stops_release_even_with_matching_request(root: Path) -> None:
    arm(root)
    ack = root / "ack.json"
    ack.write_text(json.dumps({"version": 1, "nonce": "b" * 32, "watchdog_pid": 100}))
    ack.chmod(0o600)
    raw = (root / "request.json").read_bytes()
    with pytest.raises(pause.WatchdogPauseRefused, match="ACK untrusted"):
        pause.release_pause(root, nonce=NONCE)
    assert (root / "request.json").read_bytes() == raw
    assert ack.is_file()


def test_invalid_request_fields_refuse_release(root: Path) -> None:
    arm(root, scope="tunnel")
    with pytest.raises(pause.WatchdogPauseRefused, match="request untrusted"):
        pause.release_pause(root, nonce=NONCE)
    assert (root / "request.json").exists()


def test_owner_can_release_after_request_deadline_if_producer_restored(
    root: Path,
) -> None:
    # Unlike a watchdog pause ACK, a release must not depend on the wall
    # clock: the guardian can recover a service after the request expires.
    arm(root, until=time.time() - 20)
    with pytest.raises(pause.WatchdogPauseRefused, match="invalid"):
        pause.WatchdogMaintenanceFence(root).poll()
    pause.release_pause(root, nonce=NONCE)
    assert not (root / "request.json").exists()


def test_fenced_controller_cannot_release_during_watchdog_restart(
    root: Path,
) -> None:
    arm(root)
    # A request already exists, but the restart lock is still exclusive.
    fence = pause.WatchdogMaintenanceFence(root)
    with fence.action() as allowed:
        assert not allowed
        with pytest.raises(pause.WatchdogPauseRefused, match="busy"):
            pause.release_pause(root, nonce=NONCE)
    pause.release_pause(root, nonce=NONCE)


def test_unlink_error_does_not_remove_request_or_ack(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arm(root)
    pause.WatchdogMaintenanceFence(root).poll()
    actual_unlink = pause.os.unlink

    def fail_ack(path, *args, **kwargs):
        if path == "ack.json":
            raise PermissionError("synthetic inability to remove ACK")
        return actual_unlink(path, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(pause.os, "unlink", fail_ack)
        with pytest.raises(pause.WatchdogPauseRefused, match="unprovable"):
            pause.release_pause(root, nonce=NONCE)
    assert (root / "request.json").exists()
    assert (root / "ack.json").exists()


def test_release_never_follows_foreign_request_symlink(root: Path) -> None:
    other = root / "foreign"
    other.write_bytes(b"precious")
    (root / "request.json").symlink_to(other)
    with pytest.raises(pause.WatchdogPauseRefused):
        pause.release_pause(root, nonce=NONCE)
    assert other.read_bytes() == b"precious"


def test_new_transaction_only_possible_after_release(root: Path) -> None:
    pause.request_pause(root, nonce=NONCE, until=time.time() + 90)
    with pytest.raises(pause.WatchdogPauseRefused, match="existing"):
        pause.request_pause(root, nonce="b" * 32, until=time.time() + 60)
    pause.release_pause(root, nonce=NONCE)
    pause.request_pause(root, nonce="b" * 32, until=time.time() + 60)
    assert pause.WatchdogMaintenanceFence(root).poll()
    assert not pause.confirmed_ack(root, nonce=NONCE, watchdog_pid=501)
