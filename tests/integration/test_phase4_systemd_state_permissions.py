"""Static Phase 4 systemd and setup write-authority checks."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts import setup_dev_pi


def test_systemd_runtime_and_durable_write_authority_is_narrow(repo_root: Path) -> None:
    lines = set(
        (repo_root / "deploy/systemd/binnacle-dev.service").read_text(encoding="utf-8").splitlines()
    )
    assert {
        "ProtectSystem=strict",
        "RuntimeDirectory=binnacle",
        "RuntimeDirectoryMode=0750",
        "RuntimeDirectoryPreserve=yes",
        "ReadWritePaths=/var/lib/binnacle/state",
        "ReadWritePaths=/var/lib/binnacle/results",
        "ReadWritePaths=/var/lib/binnacle/audit",
    } <= lines
    writable = {line for line in lines if line.startswith("ReadWritePaths=")}
    assert writable == {
        "ReadWritePaths=/var/lib/binnacle/state",
        "ReadWritePaths=/var/lib/binnacle/results",
        "ReadWritePaths=/var/lib/binnacle/audit",
    }
    assert all("/etc/binnacle" not in line for line in writable)
    assert all("/var/lib/binnacle/evaluation" not in line for line in writable)
    assert all("/srv/binnacle-dev/repo" not in line for line in writable)


def test_setup_declares_exact_protected_and_service_owned_roots() -> None:
    root_paths = {str(path): mode for path, mode in setup_dev_pi.ROOT_PROTECTED_PATHS}
    service_paths = {str(path): mode for path, mode in setup_dev_pi.SERVICE_STATE_PATHS}
    assert root_paths == {
        "/etc/binnacle": 0o750,
        "/var/lib/binnacle/evaluation": 0o750,
    }
    assert {
        "/var/lib/binnacle/state",
        "/var/lib/binnacle/state/checkpoints",
        "/var/lib/binnacle/state/audit-obligations",
        "/var/lib/binnacle/results",
        "/var/lib/binnacle/results/objects",
        "/var/lib/binnacle/results/streams",
        "/var/lib/binnacle/results/tmp",
        "/var/lib/binnacle/audit",
        "/var/lib/binnacle/audit/epochs",
        "/var/lib/binnacle/audit/emergency",
    } == set(service_paths)
    assert set(service_paths.values()) == {0o750}
    assert "/run/binnacle" not in root_paths | service_paths


def test_setup_rejects_symlinked_protected_path_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "unrelated-target"
    target.mkdir()
    linked = tmp_path / "state"
    linked.symlink_to(target, target_is_directory=True)
    protected = linked / "audit"
    before = target.stat()
    monkeypatch.setattr(setup_dev_pi, "SYSTEM_PATHS", ((protected, 0o750),))
    check = setup_dev_pi._check_system_path_safety()
    assert check.status == "fail"

    with pytest.raises(setup_dev_pi.SetupError, match="unsafe component"):
        setup_dev_pi._ensure_protected_directory(protected, uid=0, gid=0, mode=0o750)
    after = target.stat()
    assert (after.st_uid, after.st_gid, after.st_mode) == (
        before.st_uid,
        before.st_gid,
        before.st_mode,
    )
