"""Fail-closed fixture controller transaction faults; no live services touched."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import issue30_rehearsal_support as rehearsal
from tests.platform.darwin.test_log_quiescence_rehearsal import (
    NONCE,
    _assert_released,
    _run,
    scenario,
)

__all__ = ["scenario"]  # Import a shared pytest fixture.


@pytest.mark.parametrize("child", ["watchdog", "manager-pause", "jobs", "j7-state"])
def test_child_directory_must_remain_private(scenario, child: str) -> None:
    root, _manager, _owner, mcp = scenario
    directory = root / child
    directory.chmod(0o755)
    try:
        with pytest.raises(rehearsal.RehearsalRefused, match="child not private"):
            _run(scenario)
        assert mcp.snapshot().pause_nonce is None
    finally:
        directory.chmod(0o700)


def test_missing_fixture_root_produces_typed_refusal(scenario) -> None:
    root, _manager, _owner, mcp = scenario
    root.rename(root.with_name("missing-fixture"))
    with pytest.raises(rehearsal.RehearsalRefused, match="unavailable"):
        _run(scenario)
    assert mcp.snapshot().pause_nonce is None


@pytest.mark.parametrize("bad_pid", [0, -1, True, "100"])
def test_bad_watchdog_identity_rejected_before_any_mutation(
    scenario, bad_pid: object
) -> None:
    root, _manager, _owner, mcp = scenario
    with pytest.raises(rehearsal.RehearsalRefused, match="watchdog incarnation"):
        _run(scenario, watchdog_pid=bad_pid)
    assert not (root / "j7-state/mac-deploy-gate.lock").exists()
    assert mcp.snapshot().pause_nonce is None


def test_manager_short_write_does_not_publish_partial_request(
    scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, manager, _owner, _mcp = scenario
    counts = [0]

    def fail_write(fd: int, view: memoryview) -> int:
        counts[0] += 1
        return 0

    with monkeypatch.context() as m:
        m.setattr(rehearsal.os, "write", fail_write)
        with pytest.raises(rehearsal.RehearsalRefused, match="short write"):
            rehearsal._request_jobs(manager, root, NONCE)
    assert counts == [1]
    assert not (root / "manager-pause/request.json").exists()
    assert not list((root / "manager-pause").glob(".*.tmp"))


def test_fsync_failure_cleans_only_its_own_temp(
    scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, manager, _owner, _mcp = scenario
    original = os.fsync
    calls = [0]

    def fail_once(fd: int):
        calls[0] += 1
        if calls[0] == 1:
            raise OSError("synthetic fsync unavailable")
        return original(fd)

    with monkeypatch.context() as m:
        m.setattr(rehearsal.os, "fsync", fail_once)
        with pytest.raises(rehearsal.RehearsalRefused, match="not published"):
            rehearsal._request_jobs(manager, root, NONCE)
    assert calls == [1]
    assert not (root / "manager-pause/request.json").exists()
    assert not list((root / "manager-pause").glob(".*.tmp"))


def test_unavailable_manager_request_temp_is_not_reclaimed(
    scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, manager, _owner, _mcp = scenario
    token = "f" * 32
    temp = root / "manager-pause" / ("." + token + ".tmp")
    temp.write_bytes(b"other controller's scratch")
    temp.chmod(0o600)
    monkeypatch.setattr(rehearsal.uuid, "uuid4", lambda: SimpleNamespace(hex=token))
    with pytest.raises(rehearsal.RehearsalRefused, match="temporary"):
        rehearsal._request_jobs(manager, root, NONCE)
    assert temp.read_bytes() == b"other controller's scratch"
    assert not (root / "manager-pause/request.json").exists()


def test_temporary_request_name_swap_cannot_remove_foreign_replacement(
    scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, manager, _owner, _mcp = scenario
    token = "b" * 32
    monkeypatch.setattr(rehearsal.uuid, "uuid4", lambda: SimpleNamespace(hex=token))
    temp = root / "manager-pause" / ("." + token + ".tmp")
    protected = root / "original-request-temp"

    def substitute(source: Path, target: Path, **kwargs):
        temp.rename(protected)
        temp.write_bytes(b"new foreign file")
        temp.chmod(0o600)
        raise OSError("synthetic publication interruption")

    with monkeypatch.context() as m:
        m.setattr(rehearsal.os, "link", substitute)
        with pytest.raises(rehearsal.RehearsalRefused, match="temporary"):
            rehearsal._request_jobs(manager, root, NONCE)
    assert protected.is_file()
    assert temp.read_bytes() == b"new foreign file"
    assert not (root / "manager-pause/request.json").exists()


def test_missing_request_release_is_safe_and_idempotent(scenario) -> None:
    root, manager, _owner, _mcp = scenario
    rehearsal._release_jobs(manager, root, NONCE)
    assert not (root / "manager-pause/request.json").exists()


def test_request_release_refuses_wrong_nonce_without_deleting(
    scenario,
) -> None:
    root, manager, _owner, _mcp = scenario
    rehearsal._request_jobs(manager, root, NONCE)
    path = root / "manager-pause/request.json"
    original = path.read_bytes()
    with pytest.raises(rehearsal.RehearsalRefused, match="owner mismatch"):
        rehearsal._release_jobs(manager, root, "b" * 32)
    assert path.read_bytes() == original
    rehearsal._release_jobs(manager, root, NONCE)


def test_release_rejects_symlink_before_any_unlink(scenario) -> None:
    root, manager, _owner, _mcp = scenario
    foreign = root / "foreign"
    foreign.write_bytes(b"precious")
    request = root / "manager-pause/request.json"
    request.symlink_to(foreign)
    with pytest.raises(rehearsal.RehearsalRefused, match="cannot open"):
        rehearsal._release_jobs(manager, root, NONCE)
    assert request.is_symlink()
    assert foreign.read_bytes() == b"precious"


def test_release_rejects_foreign_regular_file_mode(scenario) -> None:
    root, manager, _owner, _mcp = scenario
    rehearsal._request_jobs(manager, root, NONCE)
    path = root / "manager-pause/request.json"
    path.chmod(0o644)
    with pytest.raises(rehearsal.RehearsalRefused, match="replaced"):
        rehearsal._release_jobs(manager, root, NONCE)
    assert path.is_file()


def test_request_replaced_after_open_does_not_unlink_replacement(
    scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, manager, _owner, _mcp = scenario
    rehearsal._request_jobs(manager, root, NONCE)
    path = root / "manager-pause/request.json"
    source = root / "old-request"
    read = rehearsal.os.open
    changes = [0]

    def swap_after_open(path_value, *args, **kwargs):
        fd = read(path_value, *args, **kwargs)
        if str(path_value) == str(path) and changes[0] == 0:
            changes[0] += 1
            path.rename(source)
            path.write_bytes(source.read_bytes())
            path.chmod(0o600)
        return fd

    with monkeypatch.context() as m:
        m.setattr(rehearsal.os, "open", swap_after_open)
        with pytest.raises(rehearsal.RehearsalRefused, match="replaced"):
            rehearsal._release_jobs(manager, root, NONCE)
    assert changes == [1]
    assert path.is_file()
    assert source.is_file()


@pytest.mark.parametrize("result", [None, 1])
def test_durable_history_probe_unknown_or_active_never_authorizes(
    scenario, monkeypatch: pytest.MonkeyPatch, result: int | None
) -> None:
    root, _manager, _owner, _mcp = scenario
    monkeypatch.setattr(rehearsal, "active_jobs", lambda path: result)
    with pytest.raises(rehearsal.RehearsalRefused, match="durable Jobs history"):
        _run(scenario)
    _assert_released(root)
