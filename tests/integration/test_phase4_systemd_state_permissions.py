"""Static Phase 4 systemd and setup write-authority checks."""

from __future__ import annotations

import json
import os
import stat
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
        "ReadWritePaths=/var/lib/binnacle/probe-workspace",
    } <= lines
    writable = {line for line in lines if line.startswith("ReadWritePaths=")}
    assert writable == {
        "ReadWritePaths=/var/lib/binnacle/state",
        "ReadWritePaths=/var/lib/binnacle/results",
        "ReadWritePaths=/var/lib/binnacle/audit",
        "ReadWritePaths=/var/lib/binnacle/probe-workspace",
    }
    assert all("/etc/binnacle" not in line for line in writable)
    assert all("/var/lib/binnacle/evaluation" not in line for line in writable)
    assert all("/srv/binnacle-dev/repo" not in line for line in writable)


def test_setup_declares_exact_protected_and_service_owned_roots() -> None:
    root_paths = {str(path): mode for path, mode in setup_dev_pi.ROOT_PROTECTED_PATHS}
    service_paths = {str(path): mode for path, mode in setup_dev_pi.SERVICE_STATE_PATHS}
    assert root_paths == {
        "/etc/binnacle": 0o750,
        "/var/lib/binnacle": 0o750,
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
    probe_paths = {str(path): mode for path, mode in setup_dev_pi.PROBE_WORKSPACE_PATHS}
    assert probe_paths == {
        "/var/lib/binnacle/probe-workspace": 0o700,
        "/var/lib/binnacle/probe-workspace/.staging": 0o700,
    }
    assert "/run/binnacle" not in root_paths | service_paths


def test_setup_creates_traversable_protected_parent_before_fresh_state_tree(
    tmp_path: Path,
) -> None:
    protected_parent = tmp_path / "var" / "lib" / "binnacle"
    service_state = protected_parent / "state"
    uid = os.getuid()
    service_gid = os.getgid()

    setup_dev_pi._ensure_protected_directory(
        protected_parent,
        uid=uid,
        gid=service_gid,
        mode=0o750,
    )
    setup_dev_pi._ensure_protected_directory(
        service_state,
        uid=uid,
        gid=service_gid,
        mode=0o750,
    )

    parent_info = protected_parent.stat()
    assert parent_info.st_uid == uid
    assert parent_info.st_gid == service_gid
    assert stat.S_IMODE(parent_info.st_mode) == 0o750
    assert parent_info.st_mode & stat.S_IXGRP
    assert service_state.is_dir()


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


def test_setup_probe_preflight_rejects_checkout_subpath_bind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "probe-data"
    source.mkdir()
    probe = tmp_path / "probe-workspace"
    probe.mkdir()
    monkeypatch.setattr(setup_dev_pi, "PROBE_ROOT", probe)
    monkeypatch.setattr(
        setup_dev_pi,
        "_run_bounded",
        lambda _command: json.dumps(
            {
                "filesystems": [
                    {
                        "target": str(probe),
                        "source": f"/dev/mmcblk0p2[{source}]",
                        "fstype": "ext4",
                        "options": "rw,bind",
                        "fsroot": str(source),
                    }
                ]
            }
        ),
    )

    check = setup_dev_pi._check_probe_mount_profile(repo)

    assert check.status == "fail"


@pytest.mark.parametrize(
    "mount",
    (
        setup_dev_pi._ProbeMountFacts(
            target=Path("/"),
            source="server:/probe",
            filesystem_type="nfs4",
            options=frozenset({"rw"}),
            filesystem_root="/",
        ),
        setup_dev_pi._ProbeMountFacts(
            target=Path("/"),
            source="/dev/mmcblk0p2",
            filesystem_type="xfs",
            options=frozenset({"rw"}),
            filesystem_root="/",
        ),
    ),
)
def test_setup_probe_preflight_rejects_network_and_unsupported_profiles(
    mount: setup_dev_pi._ProbeMountFacts,
) -> None:
    assert not setup_dev_pi._probe_mount_is_supported(
        mount,
        root_device=7,
        protected_devices=frozenset({7}),
    )


def test_setup_probe_preflight_rejects_exact_protected_device_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = Path("/var/lib/binnacle/probe-workspace")
    monkeypatch.setattr(setup_dev_pi, "PROBE_ROOT", probe)
    mount = setup_dev_pi._ProbeMountFacts(
        target=probe,
        source="/dev/mmcblk0p2",
        filesystem_type="ext4",
        options=frozenset({"rw"}),
        filesystem_root="/",
    )

    assert not setup_dev_pi._probe_mount_is_supported(
        mount,
        root_device=7,
        protected_devices=frozenset({7}),
    )


def test_setup_apply_stops_before_mutation_when_probe_mount_preflight_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    passed = setup_dev_pi.Check("fixture", "pass", "safe")
    failed = setup_dev_pi.Check("probe-mount", "fail", "unsafe alias")
    monkeypatch.setattr(setup_dev_pi, "_check_platform", lambda: passed)
    monkeypatch.setattr(setup_dev_pi, "_check_architecture", lambda: passed)
    monkeypatch.setattr(setup_dev_pi, "_check_distribution", lambda: passed)
    monkeypatch.setattr(setup_dev_pi, "_check_python", lambda: passed)
    monkeypatch.setattr(setup_dev_pi, "_check_systemd", lambda: passed)
    monkeypatch.setattr(setup_dev_pi, "_check_repository", lambda _repo: passed)
    monkeypatch.setattr(setup_dev_pi, "_check_identity_compatibility", lambda: passed)
    monkeypatch.setattr(setup_dev_pi, "_check_system_path_safety", lambda: passed)
    monkeypatch.setattr(setup_dev_pi, "_check_probe_mount_profile", lambda _repo: failed)
    mutations: list[str] = []
    monkeypatch.setattr(setup_dev_pi, "_ensure_group", lambda _name: mutations.append("group"))
    monkeypatch.setattr(setup_dev_pi, "_ensure_user", lambda: mutations.append("user"))
    monkeypatch.setattr(
        setup_dev_pi,
        "_ensure_protected_directory",
        lambda *_args, **_kwargs: mutations.append("directory"),
    )

    with pytest.raises(setup_dev_pi.SetupError, match="no changes"):
        setup_dev_pi.apply_setup(tmp_path, enable=False)

    assert mutations == []
