"""Actual manager startup wiring for private maintenance admission, default OFF."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from binnacle.platform.darwin.job_manager_config import (
    ManagerConfig,
)
from binnacle.platform.darwin.job_manager_entry import (
    configure_private_maintenance_admission,
)
from binnacle.platform.darwin.job_manager_service import PROTOCOL_VERSION
from tests.platform.darwin.test_job_manager_maintenance_fence import (
    _launch,
    _manager,
)


def test_manager_maintenance_setting_defaults_disabled() -> None:
    cfg = ManagerConfig(_env_file=None)
    assert cfg.jobs.maintenance_fence_dir is None


def test_unconfigured_manager_preserves_default_original_codepath(
    tmp_path: Path,
) -> None:
    manager, owner, _old = _manager(tmp_path)
    manager.maintenance_fence = None
    manager.maintenance_probe = None
    configure_private_maintenance_admission(manager, None)
    assert manager.maintenance_fence is None
    assert manager.maintenance_probe is None
    assert isinstance(_launch(manager, tmp_path), str)
    assert len(owner.spawned) == 1


def test_configured_private_root_stops_start_only_after_valid_pause(
    tmp_path: Path,
) -> None:
    manager, owner, old = _manager(tmp_path)
    root = tmp_path / "private-controller-root"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    manager.maintenance_fence = None
    manager.maintenance_probe = None
    configure_private_maintenance_admission(manager, root)
    assert manager.maintenance_fence is not None
    assert manager.maintenance_probe is not None
    initial = manager.dispatch({"version": PROTOCOL_VERSION, "op": "ping"})
    assert initial["maintenance_admission"] == {"state": "absent", "nonce": None}
    assert initial["running_jobs"] == initial["unknown_jobs"] == 0
    nonce = "b" * 32
    request = {
        "version": 1,
        "nonce": nonce,
        "owner_instance_id": manager.owner_instance_id,
        "pid": os.getpid(),
        "until": time.time() + 100,
        "scope": "jobs",
    }
    payload = root / "request.json"
    payload.write_text(json.dumps(request))
    payload.chmod(0o600)
    paused = manager.dispatch({"version": PROTOCOL_VERSION, "op": "ping"})
    assert paused["maintenance_admission"] == {"state": "paused", "nonce": nonce}
    assert paused["running_jobs"] == paused["unknown_jobs"] == 0
    refused = _launch(manager, tmp_path)
    assert isinstance(refused, dict) and refused["code"] == "maintenance_paused"
    assert not owner.spawned
    payload.unlink()
    subsequent = _launch(manager, tmp_path)
    assert isinstance(subsequent, str)
    assert len(owner.spawned) == 1
    assert old.exists()


@pytest.mark.parametrize("badmode", ["missing", "public", "symlink", "file"])
def test_invalid_explicit_controller_root_fails_before_installing_hooks(
    tmp_path: Path,
    badmode: str,
) -> None:
    manager, owner, _old = _manager(tmp_path)
    manager.maintenance_fence = manager.maintenance_probe = None
    root = tmp_path / "controller-root"
    if badmode == "public":
        root.mkdir(mode=0o755)
        root.chmod(0o755)
    elif badmode == "symlink":
        actual = tmp_path / "real-root"
        actual.mkdir(mode=0o700)
        root.symlink_to(actual, target_is_directory=True)
    elif badmode == "file":
        root.write_bytes(b"unexpected file")
    with pytest.raises((OSError, ValueError), match="untrusted|invalid"):
        configure_private_maintenance_admission(manager, root)
    assert manager.maintenance_fence is None
    assert manager.maintenance_probe is None
    assert not owner.spawned


@pytest.mark.parametrize("bad", ["relative", "/tmp/../bad"])
def test_invalid_controller_root_path_is_not_a_maintenance_root(
    tmp_path: Path, bad: str
) -> None:
    manager, _owner, _ = _manager(tmp_path)
    with pytest.raises(ValueError, match="invalid"):
        configure_private_maintenance_admission(manager, Path(bad))


def test_spool_root_must_never_be_used_as_controller_root(tmp_path: Path) -> None:
    manager, _owner, _ = _manager(tmp_path)
    with pytest.raises(ValueError, match="invalid"):
        configure_private_maintenance_admission(manager, manager.jobs_dir)


def test_corrupted_pause_keeps_starts_refused_in_configured_manager(
    tmp_path: Path,
) -> None:
    manager, owner, _ = _manager(tmp_path)
    root = tmp_path / "controller-root"
    root.mkdir(mode=0o700)
    configure_private_maintenance_admission(manager, root)
    (root / "request.json").write_text("this is malformed")
    (root / "request.json").chmod(0o600)
    reply = manager.dispatch({"version": PROTOCOL_VERSION, "op": "ping"})
    assert reply["maintenance_admission"] == {"state": "unknown", "nonce": None}
    refused = _launch(manager, tmp_path)
    assert refused["code"] == "maintenance_state_unknown"
    assert not owner.spawned
