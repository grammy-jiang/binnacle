"""Descriptor-relative Linux probe boundary tests."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from binnacle.adapters.probe_workspace import (
    LinuxProbeWorkspace,
    ProbeEffectNotStarted,
    ProbeWorkspaceFilesystemError,
)
from binnacle.domain.probe_workspace import ProbeTargetState


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "probe"
    (root / ".staging").mkdir(parents=True)
    root.chmod(0o700)
    (root / ".staging").chmod(0o700)
    return root


@pytest.mark.anyio
async def test_linux_probe_create_is_no_replace_and_cleanup_is_identity_bound(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    workspace = LinuxProbeWorkspace(root=root, maximum_file_bytes=65_536)
    await workspace.initialize()
    content = b"bounded probe"
    digest = hashlib.sha256(content).hexdigest()
    reference = await workspace.create(
        operation_id="op_fixture",
        artifact_id="artifact_fixture",
        path_generation=1,
        relative_path="probe.txt",
        content=content,
        expected_content_sha256=digest,
    )
    observation = await workspace.observe("probe.txt")
    assert observation.state is ProbeTargetState.EXACT
    assert observation.content_sha256 == digest
    assert reference.endswith(observation.file_identity_digest or "missing")
    with pytest.raises(ProbeEffectNotStarted):
        await workspace.create(
            operation_id="op_second",
            artifact_id="artifact_second",
            path_generation=2,
            relative_path="probe.txt",
            content=b"replacement",
            expected_content_sha256=hashlib.sha256(b"replacement").hexdigest(),
        )
    assert (root / "probe.txt").read_bytes() == content
    with pytest.raises(ProbeEffectNotStarted):
        await workspace.remove(
            operation_id="op_cleanup",
            artifact_id="artifact_fixture",
            path_generation=1,
            relative_path="probe.txt",
            expected_content_sha256=digest,
            expected_file_identity_digest="f" * 64,
        )
    await workspace.remove(
        operation_id="op_cleanup",
        artifact_id="artifact_fixture",
        path_generation=1,
        relative_path="probe.txt",
        expected_content_sha256=digest,
        expected_file_identity_digest=observation.file_identity_digest or "",
    )
    assert (await workspace.observe("probe.txt")).state is ProbeTargetState.ABSENT
    tombs = tuple((root / ".staging").iterdir())
    assert len(tombs) == 1
    assert tombs[0].name.startswith(".binnacle-cleanup-tomb-v1-")
    assert tombs[0].read_bytes() == content


@pytest.mark.anyio
async def test_linux_probe_rejects_symlinked_root_or_staging(tmp_path: Path) -> None:
    real = _root(tmp_path)
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(ProbeWorkspaceFilesystemError, match=r"layout|directory|root"):
        await LinuxProbeWorkspace(root=linked, maximum_file_bytes=100).initialize()


@pytest.mark.anyio
async def test_linux_probe_layout_identity_and_constructor_bounds(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        LinuxProbeWorkspace(root=Path("relative"))
    with pytest.raises(ValueError, match="byte limit"):
        LinuxProbeWorkspace(root=tmp_path.resolve(), maximum_file_bytes=0)

    root = _root(tmp_path)
    workspace = LinuxProbeWorkspace(root=root, maximum_file_bytes=16)
    await workspace.initialize()
    identity = await workspace.root_identity()
    assert workspace.root == root
    assert identity.inode == root.stat().st_ino
    assert identity.mode == 0o700

    root.chmod(0o750)
    with pytest.raises(ProbeWorkspaceFilesystemError, match="unsafe"):
        await workspace.root_identity()


@pytest.mark.anyio
async def test_linux_probe_detects_replaced_root_identity(tmp_path: Path) -> None:
    root = _root(tmp_path)
    workspace = LinuxProbeWorkspace(root=root, maximum_file_bytes=16)
    await workspace.initialize()
    root.rename(tmp_path / "old-probe")
    replacement = _root(tmp_path)
    assert replacement == root

    with pytest.raises(ProbeWorkspaceFilesystemError, match="identity changed"):
        await workspace.root_identity()


@pytest.mark.anyio
async def test_linux_probe_effect_fds_reject_replaced_root_or_staging(tmp_path: Path) -> None:
    content = b"safe"
    digest = hashlib.sha256(content).hexdigest()
    root = _root(tmp_path / "root-replaced")
    workspace = LinuxProbeWorkspace(root=root, maximum_file_bytes=16)
    await workspace.initialize()
    root.rename(root.parent / "old-probe")
    replacement = _root(root.parent)

    with pytest.raises(ProbeWorkspaceFilesystemError, match="identity changed before effect"):
        await workspace.create(
            operation_id="op-fixture",
            artifact_id="artifact-fixture",
            path_generation=1,
            relative_path="probe.txt",
            content=content,
            expected_content_sha256=digest,
        )
    assert not (replacement / "probe.txt").exists()

    root = _root(tmp_path / "staging-replaced")
    workspace = LinuxProbeWorkspace(root=root, maximum_file_bytes=16)
    await workspace.initialize()
    staging = root / ".staging"
    staging.rename(root / ".staging-old")
    staging.mkdir(mode=0o700)

    with pytest.raises(ProbeWorkspaceFilesystemError, match="identity changed before effect"):
        await workspace.create(
            operation_id="op-fixture",
            artifact_id="artifact-fixture",
            path_generation=1,
            relative_path="probe.txt",
            content=content,
            expected_content_sha256=digest,
        )
    assert not (root / "probe.txt").exists()


@pytest.mark.anyio
async def test_linux_probe_observation_rejects_non_regular_or_broad_files(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    workspace = LinuxProbeWorkspace(root=root, maximum_file_bytes=4)
    await workspace.initialize()

    (root / "directory").mkdir()
    assert (await workspace.observe("directory")).state is ProbeTargetState.MISMATCH

    (root / "broad.txt").write_bytes(b"12345")
    (root / "broad.txt").chmod(0o600)
    assert (await workspace.observe("broad.txt")).state is ProbeTargetState.MISMATCH

    (root / "wrong-mode.txt").write_bytes(b"1234")
    (root / "wrong-mode.txt").chmod(0o640)
    assert (await workspace.observe("wrong-mode.txt")).state is ProbeTargetState.MISMATCH

    (root / "target.txt").write_bytes(b"1234")
    (root / "target.txt").chmod(0o600)
    (root / "linked.txt").symlink_to(root / "target.txt")
    assert (await workspace.observe("linked.txt")).state is ProbeTargetState.MISMATCH


@pytest.mark.anyio
async def test_linux_probe_bounds_digest_and_absent_cleanup_are_known_no_effect(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    workspace = LinuxProbeWorkspace(root=root, maximum_file_bytes=4)
    await workspace.initialize()

    with pytest.raises(ProbeEffectNotStarted, match="bounds"):
        await workspace.create(
            operation_id="op_fixture",
            artifact_id="artifact_fixture",
            path_generation=0,
            relative_path="probe.txt",
            content=b"1234",
            expected_content_sha256=hashlib.sha256(b"1234").hexdigest(),
        )
    with pytest.raises(ProbeEffectNotStarted, match="digest"):
        await workspace.create(
            operation_id="op_fixture",
            artifact_id="artifact_fixture",
            path_generation=1,
            relative_path="probe.txt",
            content=b"1234",
            expected_content_sha256="a" * 64,
        )
    assert (
        await workspace.remove(
            operation_id="op_cleanup",
            artifact_id="artifact_fixture",
            path_generation=1,
            relative_path="missing.txt",
            expected_content_sha256="a" * 64,
            expected_file_identity_digest="b" * 64,
        )
        is None
    )
    with pytest.raises(ProbeEffectNotStarted, match="generation"):
        await workspace.remove(
            operation_id="op_cleanup",
            artifact_id="artifact_fixture",
            path_generation=0,
            relative_path="missing.txt",
            expected_content_sha256="a" * 64,
            expected_file_identity_digest="b" * 64,
        )


def test_linux_probe_low_level_io_helpers_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = LinuxProbeWorkspace(root=tmp_path.resolve(), maximum_file_bytes=4)
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, b"12345")
        os.close(write_fd)
        write_fd = -1
        with pytest.raises(ProbeWorkspaceFilesystemError, match="structural bound"):
            workspace._read_bounded(read_fd)
    finally:
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)

    monkeypatch.setattr(os, "write", lambda _descriptor, _content: 0)
    with pytest.raises(OSError, match="short"):
        workspace._write_all(1, b"x")


@pytest.mark.anyio
async def test_linux_probe_descriptor_open_races_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    workspace = LinuxProbeWorkspace(root=root, maximum_file_bytes=8)
    await workspace.initialize()
    real_open = os.open
    open_count = 0

    def fail_second_open(*args: object, **kwargs: object) -> int:
        nonlocal open_count
        open_count += 1
        if open_count == 2:
            raise OSError("staging raced")
        return real_open(*args, **kwargs)  # type: ignore[arg-type]

    with monkeypatch.context() as patcher:
        patcher.setattr(os, "open", fail_second_open)
        with pytest.raises(OSError, match="staging raced"):
            workspace._open_directories()

    target = root / "probe.txt"
    target.write_bytes(b"safe")
    target.chmod(0o600)
    root_fd = real_open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:

        def fail_target_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            if path == "probe.txt":
                raise OSError("target raced")
            return real_open(path, flags, mode, dir_fd=dir_fd)

        with monkeypatch.context() as patcher:
            patcher.setattr(os, "open", fail_target_open)
            assert workspace._observe_at(root_fd, "probe.txt").state is ProbeTargetState.MISMATCH
    finally:
        os.close(root_fd)


@pytest.mark.anyio
async def test_linux_probe_create_faults_preserve_no_start_vs_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"safe"
    digest = hashlib.sha256(content).hexdigest()

    root = _root(tmp_path / "staging-mismatch")
    workspace = LinuxProbeWorkspace(root=root, maximum_file_bytes=8)
    await workspace.initialize()
    with monkeypatch.context() as patcher:
        patcher.setattr(workspace, "_read_bounded", lambda _descriptor: b"wrong")
        with pytest.raises(ProbeEffectNotStarted, match="staging_verification"):
            await workspace.create(
                operation_id="op-fixture",
                artifact_id="artifact-fixture",
                path_generation=1,
                relative_path="probe.txt",
                content=content,
                expected_content_sha256=digest,
            )
    assert not (root / "probe.txt").exists()

    root = _root(tmp_path / "link-race")
    workspace = LinuxProbeWorkspace(root=root, maximum_file_bytes=8)
    await workspace.initialize()
    with monkeypatch.context() as patcher:

        def target_exists(*_args: object, **_kwargs: object) -> None:
            raise FileExistsError("target appeared")

        patcher.setattr(os, "link", target_exists)
        with pytest.raises(ProbeEffectNotStarted, match="target_not_absent"):
            await workspace.create(
                operation_id="op-fixture",
                artifact_id="artifact-fixture",
                path_generation=1,
                relative_path="probe.txt",
                content=content,
                expected_content_sha256=digest,
            )

    root = _root(tmp_path / "pre-publish")
    workspace = LinuxProbeWorkspace(root=root, maximum_file_bytes=8)
    await workspace.initialize()
    with monkeypatch.context() as patcher:
        patcher.setattr(os, "fsync", lambda _descriptor: (_ for _ in ()).throw(OSError("disk")))
        with pytest.raises(ProbeEffectNotStarted, match="write_not_started"):
            await workspace.create(
                operation_id="op-fixture",
                artifact_id="artifact-fixture",
                path_generation=1,
                relative_path="probe.txt",
                content=content,
                expected_content_sha256=digest,
            )
    assert not (root / "probe.txt").exists()

    root = _root(tmp_path / "post-publish")
    workspace = LinuxProbeWorkspace(root=root, maximum_file_bytes=8)
    await workspace.initialize()
    real_fsync = os.fsync

    def fail_root_fsync(descriptor: int) -> None:
        if os.fstat(descriptor).st_ino == root.stat().st_ino:
            raise OSError("root fsync failed")
        real_fsync(descriptor)

    with monkeypatch.context() as patcher:
        patcher.setattr(os, "fsync", fail_root_fsync)
        with pytest.raises(OSError, match="root fsync failed"):
            await workspace.create(
                operation_id="op-fixture",
                artifact_id="artifact-fixture",
                path_generation=1,
                relative_path="probe.txt",
                content=content,
                expected_content_sha256=digest,
            )
    assert (root / "probe.txt").read_bytes() == content


@pytest.mark.anyio
async def test_linux_probe_cleanup_races_are_conservatively_classified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    workspace = LinuxProbeWorkspace(root=root, maximum_file_bytes=8)
    await workspace.initialize()
    content = b"safe"
    digest = hashlib.sha256(content).hexdigest()
    await workspace.create(
        operation_id="op-write",
        artifact_id="artifact-fixture",
        path_generation=1,
        relative_path="probe.txt",
        content=content,
        expected_content_sha256=digest,
    )
    exact = await workspace.observe("probe.txt")
    assert exact.file_identity_digest is not None

    real_rename_noreplace = workspace._rename_noreplace
    substituted = False

    def substitute_before_quarantine(
        *,
        source_dir_fd: int,
        source_name: str,
        destination_dir_fd: int,
        destination_name: str,
    ) -> None:
        nonlocal substituted
        if source_name == "probe.txt" and not substituted:
            substituted = True
            os.rename(
                source_name,
                "original-survives.txt",
                src_dir_fd=source_dir_fd,
                dst_dir_fd=source_dir_fd,
            )
            replacement = os.open(
                source_name,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
                dir_fd=source_dir_fd,
            )
            try:
                os.write(replacement, b"other")
            finally:
                os.close(replacement)
        real_rename_noreplace(
            source_dir_fd=source_dir_fd,
            source_name=source_name,
            destination_dir_fd=destination_dir_fd,
            destination_name=destination_name,
        )

    with monkeypatch.context() as patcher:
        patcher.setattr(workspace, "_rename_noreplace", substitute_before_quarantine)
        with pytest.raises(ProbeEffectNotStarted, match="identity_changed"):
            await workspace.remove(
                operation_id="op-cleanup",
                artifact_id="artifact-fixture",
                path_generation=1,
                relative_path="probe.txt",
                expected_content_sha256=digest,
                expected_file_identity_digest=exact.file_identity_digest,
            )
    assert (root / "original-survives.txt").read_bytes() == content
    assert (root / "probe.txt").read_bytes() == b"other"
    assert tuple((root / ".staging").iterdir()) == ()

    (root / "probe.txt").unlink()
    (root / "original-survives.txt").rename(root / "probe.txt")

    def disappear_before_quarantine(
        *,
        source_dir_fd: int,
        source_name: str,
        destination_dir_fd: int,
        destination_name: str,
    ) -> None:
        if source_name == "probe.txt":
            raise FileNotFoundError("raced")
        real_rename_noreplace(
            source_dir_fd=source_dir_fd,
            source_name=source_name,
            destination_dir_fd=destination_dir_fd,
            destination_name=destination_name,
        )

    with monkeypatch.context() as patcher:
        patcher.setattr(workspace, "_rename_noreplace", disappear_before_quarantine)
        assert (
            await workspace.remove(
                operation_id="op-cleanup",
                artifact_id="artifact-fixture",
                path_generation=1,
                relative_path="probe.txt",
                expected_content_sha256=digest,
                expected_file_identity_digest=exact.file_identity_digest,
            )
            is None
        )

    real_fsync = os.fsync

    def fail_root_fsync(descriptor: int) -> None:
        if os.fstat(descriptor).st_ino == root.stat().st_ino:
            raise OSError("root fsync failed")
        real_fsync(descriptor)

    with monkeypatch.context() as patcher:
        patcher.setattr(os, "fsync", fail_root_fsync)
        with pytest.raises(OSError, match="root fsync failed"):
            await workspace.remove(
                operation_id="op-cleanup",
                artifact_id="artifact-fixture",
                path_generation=1,
                relative_path="probe.txt",
                expected_content_sha256=digest,
                expected_file_identity_digest=exact.file_identity_digest,
            )
    assert not (root / "probe.txt").exists()


@pytest.mark.anyio
async def test_linux_probe_cleanup_retains_held_inode_when_target_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    workspace = LinuxProbeWorkspace(root=root, maximum_file_bytes=16)
    await workspace.initialize()
    content = b"safe"
    digest = hashlib.sha256(content).hexdigest()
    await workspace.create(
        operation_id="op-write",
        artifact_id="artifact-fixture",
        path_generation=1,
        relative_path="probe.txt",
        content=content,
        expected_content_sha256=digest,
    )
    observation = await workspace.observe("probe.txt")
    assert observation.file_identity_digest is not None
    original_inode = (root / "probe.txt").stat().st_ino
    real_observe_descriptor = workspace._observe_descriptor

    def replace_after_quarantine(descriptor: int) -> object:
        verified = real_observe_descriptor(descriptor)
        replacement = root / "probe.txt"
        replacement.write_bytes(b"unrelated")
        replacement.chmod(0o600)
        return verified

    with monkeypatch.context() as patcher:
        patcher.setattr(workspace, "_observe_descriptor", replace_after_quarantine)
        with pytest.raises(ProbeWorkspaceFilesystemError, match="replaced after quarantine"):
            await workspace.remove(
                operation_id="op-cleanup",
                artifact_id="artifact-fixture",
                path_generation=1,
                relative_path="probe.txt",
                expected_content_sha256=digest,
                expected_file_identity_digest=observation.file_identity_digest,
            )

    assert (root / "probe.txt").read_bytes() == b"unrelated"
    tombs = tuple((root / ".staging").iterdir())
    assert len(tombs) == 1
    assert tombs[0].stat().st_ino == original_inode
    assert tombs[0].read_bytes() == content


@pytest.mark.anyio
async def test_linux_probe_cleanup_rejects_hard_link_without_mutating_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    workspace = LinuxProbeWorkspace(root=root, maximum_file_bytes=16)
    await workspace.initialize()
    content = b"safe"
    digest = hashlib.sha256(content).hexdigest()
    await workspace.create(
        operation_id="op-write",
        artifact_id="artifact-fixture",
        path_generation=1,
        relative_path="probe.txt",
        content=content,
        expected_content_sha256=digest,
    )
    observation = await workspace.observe("probe.txt")
    assert observation.file_identity_digest is not None
    real_observe_descriptor = workspace._observe_descriptor
    preexisting_alias = tmp_path / "preexisting-alias.txt"
    external_alias = tmp_path / "external-alias.txt"

    os.link(root / "probe.txt", preexisting_alias)
    with pytest.raises(ProbeEffectNotStarted, match="identity_mismatch"):
        await workspace.remove(
            operation_id="op-cleanup-preexisting",
            artifact_id="artifact-fixture",
            path_generation=1,
            relative_path="probe.txt",
            expected_content_sha256=digest,
            expected_file_identity_digest=observation.file_identity_digest,
        )
    assert (root / "probe.txt").read_bytes() == content
    assert preexisting_alias.read_bytes() == content
    preexisting_alias.unlink()

    def link_after_quarantine_observation(descriptor: int) -> object:
        verified = real_observe_descriptor(descriptor)
        tomb = next((root / ".staging").iterdir())
        os.link(tomb, external_alias)
        return verified

    with monkeypatch.context() as patcher:
        patcher.setattr(
            workspace,
            "_observe_descriptor",
            link_after_quarantine_observation,
        )
        with pytest.raises(ProbeEffectNotStarted, match="hardlink_detected"):
            await workspace.remove(
                operation_id="op-cleanup",
                artifact_id="artifact-fixture",
                path_generation=1,
                relative_path="probe.txt",
                expected_content_sha256=digest,
                expected_file_identity_digest=observation.file_identity_digest,
            )

    assert (root / "probe.txt").read_bytes() == content
    assert external_alias.read_bytes() == content
    assert tuple((root / ".staging").iterdir()) == ()


@pytest.mark.anyio
async def test_linux_probe_observations_reject_hard_link_races(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    workspace = LinuxProbeWorkspace(root=root, maximum_file_bytes=16)
    await workspace.initialize()
    content = b"safe"
    digest = hashlib.sha256(content).hexdigest()
    await workspace.create(
        operation_id="op-write",
        artifact_id="artifact-fixture",
        path_generation=1,
        relative_path="probe.txt",
        content=content,
        expected_content_sha256=digest,
    )
    exact = await workspace.observe("probe.txt")
    assert exact.file_identity_digest is not None
    alias = tmp_path / "external-alias.txt"
    real_read_bounded = workspace._read_bounded

    def link_during_root_read(descriptor: int) -> bytes:
        observed = real_read_bounded(descriptor)
        os.link(root / "probe.txt", alias)
        return observed

    with monkeypatch.context() as patcher:
        patcher.setattr(workspace, "_read_bounded", link_during_root_read)
        assert (await workspace.observe("probe.txt")).state is ProbeTargetState.MISMATCH
    assert (root / "probe.txt").read_bytes() == content
    assert alias.read_bytes() == content
    alias.unlink()

    real_rename_noreplace = workspace._rename_noreplace

    def link_immediately_after_quarantine(
        *,
        source_dir_fd: int,
        source_name: str,
        destination_dir_fd: int,
        destination_name: str,
    ) -> None:
        real_rename_noreplace(
            source_dir_fd=source_dir_fd,
            source_name=source_name,
            destination_dir_fd=destination_dir_fd,
            destination_name=destination_name,
        )
        if source_name == "probe.txt":
            os.link(root / ".staging" / destination_name, alias)

    with monkeypatch.context() as patcher:
        patcher.setattr(workspace, "_rename_noreplace", link_immediately_after_quarantine)
        with pytest.raises(ProbeEffectNotStarted, match="identity_changed"):
            await workspace.remove(
                operation_id="op-cleanup-after-move",
                artifact_id="artifact-fixture",
                path_generation=1,
                relative_path="probe.txt",
                expected_content_sha256=digest,
                expected_file_identity_digest=exact.file_identity_digest,
            )
    assert (root / "probe.txt").read_bytes() == content
    assert alias.read_bytes() == content
    assert tuple((root / ".staging").iterdir()) == ()
    alias.unlink()

    read_count = 0

    def link_during_quarantine_read(descriptor: int) -> bytes:
        nonlocal read_count
        observed = real_read_bounded(descriptor)
        read_count += 1
        if read_count == 2:
            tomb = next((root / ".staging").iterdir())
            os.link(tomb, alias)
        return observed

    with monkeypatch.context() as patcher:
        patcher.setattr(workspace, "_read_bounded", link_during_quarantine_read)
        with pytest.raises(ProbeEffectNotStarted, match="identity_changed"):
            await workspace.remove(
                operation_id="op-cleanup-during-read",
                artifact_id="artifact-fixture",
                path_generation=1,
                relative_path="probe.txt",
                expected_content_sha256=digest,
                expected_file_identity_digest=exact.file_identity_digest,
            )
    assert read_count == 2
    assert (root / "probe.txt").read_bytes() == content
    assert alias.read_bytes() == content
    assert tuple((root / ".staging").iterdir()) == ()


@pytest.mark.anyio
async def test_linux_probe_hard_link_races_retain_uncertain_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"safe"
    digest = hashlib.sha256(content).hexdigest()

    root = _root(tmp_path / "restore-failure")
    workspace = LinuxProbeWorkspace(root=root, maximum_file_bytes=16)
    await workspace.initialize()
    await workspace.create(
        operation_id="op-write",
        artifact_id="artifact-fixture",
        path_generation=1,
        relative_path="probe.txt",
        content=content,
        expected_content_sha256=digest,
    )
    exact = await workspace.observe("probe.txt")
    assert exact.file_identity_digest is not None
    alias = tmp_path / "restore-failure-alias.txt"
    real_observe_descriptor = workspace._observe_descriptor

    def link_after_observation(descriptor: int) -> object:
        verified = real_observe_descriptor(descriptor)
        os.link(next((root / ".staging").iterdir()), alias)
        return verified

    with monkeypatch.context() as patcher:
        patcher.setattr(workspace, "_observe_descriptor", link_after_observation)
        patcher.setattr(
            workspace,
            "_restore_quarantine",
            lambda **_arguments: (_ for _ in ()).throw(OSError("restore blocked")),
        )
        with pytest.raises(ProbeWorkspaceFilesystemError, match="could not be restored"):
            await workspace.remove(
                operation_id="op-cleanup",
                artifact_id="artifact-fixture",
                path_generation=1,
                relative_path="probe.txt",
                expected_content_sha256=digest,
                expected_file_identity_digest=exact.file_identity_digest,
            )
    assert not (root / "probe.txt").exists()
    assert alias.read_bytes() == content
    tombs = tuple((root / ".staging").iterdir())
    assert len(tombs) == 1
    assert tombs[0].read_bytes() == content

    root = _root(tmp_path / "late-link")
    workspace = LinuxProbeWorkspace(root=root, maximum_file_bytes=16)
    await workspace.initialize()
    await workspace.create(
        operation_id="op-write-late",
        artifact_id="artifact-late",
        path_generation=1,
        relative_path="probe.txt",
        content=content,
        expected_content_sha256=digest,
    )
    exact = await workspace.observe("probe.txt")
    assert exact.file_identity_digest is not None
    alias = tmp_path / "late-link-alias.txt"
    real_observe_at = workspace._observe_at

    def link_before_final_check(root_fd: int, relative_path: str) -> object:
        observed = real_observe_at(root_fd, relative_path)
        if observed.state is ProbeTargetState.ABSENT and not alias.exists():
            os.link(next((root / ".staging").iterdir()), alias)
        return observed

    with monkeypatch.context() as patcher:
        patcher.setattr(workspace, "_observe_at", link_before_final_check)
        with pytest.raises(ProbeWorkspaceFilesystemError, match="gained a hard-link"):
            await workspace.remove(
                operation_id="op-cleanup-late",
                artifact_id="artifact-late",
                path_generation=1,
                relative_path="probe.txt",
                expected_content_sha256=digest,
                expected_file_identity_digest=exact.file_identity_digest,
            )
    assert not (root / "probe.txt").exists()
    assert alias.read_bytes() == content
    tombs = tuple((root / ".staging").iterdir())
    assert len(tombs) == 1
    assert tombs[0].read_bytes() == content


@pytest.mark.anyio
async def test_linux_probe_cleanup_collision_and_failed_restore_retain_every_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    workspace = LinuxProbeWorkspace(root=root, maximum_file_bytes=16)
    await workspace.initialize()
    content = b"safe"
    digest = hashlib.sha256(content).hexdigest()
    await workspace.create(
        operation_id="op-write",
        artifact_id="artifact-fixture",
        path_generation=1,
        relative_path="probe.txt",
        content=content,
        expected_content_sha256=digest,
    )
    observation = await workspace.observe("probe.txt")
    assert observation.file_identity_digest is not None

    def quarantine_collision(**_arguments: object) -> None:
        raise FileExistsError("private quarantine collision")

    with monkeypatch.context() as patcher:
        patcher.setattr(workspace, "_rename_noreplace", quarantine_collision)
        with pytest.raises(ProbeEffectNotStarted, match="quarantine_collision"):
            await workspace.remove(
                operation_id="op-cleanup",
                artifact_id="artifact-fixture",
                path_generation=1,
                relative_path="probe.txt",
                expected_content_sha256=digest,
                expected_file_identity_digest=observation.file_identity_digest,
            )
    assert (root / "probe.txt").read_bytes() == content
    assert tuple((root / ".staging").iterdir()) == ()

    real_rename_noreplace = workspace._rename_noreplace
    rename_count = 0

    def substitute_then_block_restore(
        *,
        source_dir_fd: int,
        source_name: str,
        destination_dir_fd: int,
        destination_name: str,
    ) -> None:
        nonlocal rename_count
        rename_count += 1
        if rename_count == 1:
            os.rename(
                source_name,
                "original-survives.txt",
                src_dir_fd=source_dir_fd,
                dst_dir_fd=source_dir_fd,
            )
            replacement = os.open(
                source_name,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
                dir_fd=source_dir_fd,
            )
            try:
                os.write(replacement, b"other")
            finally:
                os.close(replacement)
        else:
            blocker = os.open(
                destination_name,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
                dir_fd=destination_dir_fd,
            )
            try:
                os.write(blocker, b"blocker")
            finally:
                os.close(blocker)
        real_rename_noreplace(
            source_dir_fd=source_dir_fd,
            source_name=source_name,
            destination_dir_fd=destination_dir_fd,
            destination_name=destination_name,
        )

    with monkeypatch.context() as patcher:
        patcher.setattr(workspace, "_rename_noreplace", substitute_then_block_restore)
        with pytest.raises(ProbeWorkspaceFilesystemError, match="could not be restored"):
            await workspace.remove(
                operation_id="op-cleanup",
                artifact_id="artifact-fixture",
                path_generation=1,
                relative_path="probe.txt",
                expected_content_sha256=digest,
                expected_file_identity_digest=observation.file_identity_digest,
            )

    assert rename_count == 2
    assert (root / "original-survives.txt").read_bytes() == content
    assert (root / "probe.txt").read_bytes() == b"blocker"
    quarantined = tuple((root / ".staging").iterdir())
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == b"other"
