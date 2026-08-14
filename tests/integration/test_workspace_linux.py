"""Descriptor-relative, mount-aware Phase 6 Linux workspace tests."""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path

import pytest

from binnacle.adapters.workspace import (
    LinuxWorkspace,
    WorkspaceCapabilityUnavailable,
    WorkspaceEffectNotStarted,
    WorkspaceEffectUncertain,
    WorkspaceFilesystemError,
)
from binnacle.domain.workspace import (
    ContentReadPermit,
    MountIdentity,
    WorkspaceMutationKind,
    WorkspaceObjectKind,
    canonical_sha256,
)
from binnacle.ports.workspace import (
    WorkspaceCreateIntent,
    WorkspaceInspectRequest,
    WorkspaceListRequest,
    WorkspaceReadRequest,
    WorkspaceWriteIntent,
)

PROFILE_SHA256 = "a" * 64


@pytest.fixture(autouse=True)
def _model_supported_unlabelled_workspace_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run positive behavior tests as the supported no-xattr Bootstrap profile."""

    real_listxattr = os.listxattr

    def without_selinux_label(descriptor: int) -> list[str]:
        return [
            attribute for attribute in real_listxattr(descriptor) if attribute != "security.selinux"
        ]

    monkeypatch.setattr(os, "listxattr", without_selinux_label)


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    return root


def test_linux_workspace_rejects_lexical_root_escape() -> None:
    with pytest.raises(ValueError, match="canonical non-root"):
        _workspace(Path("/tmp/.."))


def _workspace(root: Path, **overrides: object) -> LinuxWorkspace:
    return LinuxWorkspace(
        root=root,
        workspace_id="binnacle-source",
        profile_sha256=PROFILE_SHA256,
        **overrides,  # type: ignore[arg-type]
    )


def _permit(
    root_identity_sha256: str,
    mount_sha256: str,
    *,
    relative_path: str,
    offset: int,
    maximum_bytes: int,
) -> ContentReadPermit:
    session_id = "session-fixture"
    return ContentReadPermit(
        permit_id="permit-fixture",
        session_id=session_id,
        session_state_version=2,
        workspace_id="binnacle-source",
        workspace_profile_sha256=PROFILE_SHA256,
        root_identity_sha256=root_identity_sha256,
        mount_identity_sha256=mount_sha256,
        request_sha256=canonical_sha256(
            {
                "maximum_bytes": maximum_bytes,
                "offset": offset,
                "relative_path": relative_path,
                "session_id": session_id,
                "workspace_id": "binnacle-source",
            }
        ),
        content_guard_epoch=1,
    )


@pytest.mark.anyio
async def test_linux_workspace_pins_root_mount_and_rechecks_configured_path(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    workspace = _workspace(root)
    identity = await workspace.initialize()
    try:
        assert identity.inode == root.stat().st_ino
        assert identity.mount.mount_id > 0
        assert identity.mount.filesystem_type
        assert await workspace.root_identity() == identity

        root.rename(tmp_path / "old-workspace")
        replacement = _root(tmp_path)
        with pytest.raises(WorkspaceFilesystemError, match=r"root|path|changed"):
            await workspace.root_identity()
        with pytest.raises(WorkspaceEffectNotStarted, match="not_started"):
            await workspace.create(
                WorkspaceCreateIntent(
                    operation_id="operation-after-root-replacement",
                    relative_path="unexpected",
                    kind=WorkspaceObjectKind.REGULAR_FILE,
                    content=b"blocked",
                    mode=0o644,
                    expected_root_identity_sha256=identity.identity_sha256,
                    expected_mount_identity_sha256=identity.mount.digest_sha256,
                )
            )
        assert not (replacement / "unexpected").exists()
    finally:
        await workspace.close()


@pytest.mark.anyio
async def test_linux_workspace_inspect_list_and_read_enforce_content_boundaries(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    (root / "src").mkdir()
    content = b"alpha\nbeta\n"
    (root / "src" / "main.py").write_bytes(content)
    (root / "linked-source.py").write_bytes(b"multiply linked")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("secret-ish metadata", encoding="utf-8")
    (root / "linked.py").hardlink_to(root / "linked-source.py")
    (root / "source-link").symlink_to("src", target_is_directory=True)
    workspace = _workspace(root)
    identity = await workspace.initialize()
    mount_sha256 = identity.mount.digest_sha256
    try:
        inspected = await workspace.inspect(
            WorkspaceInspectRequest(
                relative_path="src/main.py",
                expected_root_identity_sha256=identity.identity_sha256,
                expected_mount_identity_sha256=mount_sha256,
                include_content_digest=True,
                maximum_hash_bytes=1024,
            )
        )
        assert inspected.kind is WorkspaceObjectKind.REGULAR_FILE
        assert inspected.object_identity.content_sha256 == hashlib.sha256(content).hexdigest()

        inspected_root = await workspace.inspect(
            WorkspaceInspectRequest(
                relative_path="",
                expected_root_identity_sha256=identity.identity_sha256,
                expected_mount_identity_sha256=mount_sha256,
            )
        )
        assert inspected_root.relative_path == ""
        assert inspected_root.kind is WorkspaceObjectKind.DIRECTORY

        listing = await workspace.list(
            WorkspaceListRequest(
                relative_path="",
                expected_root_identity_sha256=identity.identity_sha256,
                expected_mount_identity_sha256=mount_sha256,
                maximum_entries=32,
            )
        )
        assert {item.relative_path for item in listing.entries} == {"source-link", "src"}
        assert listing.truncated  # protected .git and multiply-linked content were omitted.

        result = await workspace.read(
            WorkspaceReadRequest(
                relative_path="src/main.py",
                expected_root_identity_sha256=identity.identity_sha256,
                expected_mount_identity_sha256=mount_sha256,
                permit=_permit(
                    identity.identity_sha256,
                    mount_sha256,
                    relative_path="src/main.py",
                    offset=6,
                    maximum_bytes=5,
                ),
                offset=6,
                maximum_bytes=5,
            )
        )
        assert result.content == b"beta\n"
        assert result.complete
        assert result.content_sha256 == hashlib.sha256(content).hexdigest()

        with pytest.raises((WorkspaceFilesystemError, ValueError), match="protected"):
            await workspace.read(
                WorkspaceReadRequest(
                    relative_path=".git/config",
                    expected_root_identity_sha256=identity.identity_sha256,
                    expected_mount_identity_sha256=mount_sha256,
                    permit=_permit(
                        identity.identity_sha256,
                        mount_sha256,
                        relative_path=".git/config",
                        offset=0,
                        maximum_bytes=32,
                    ),
                    offset=0,
                    maximum_bytes=32,
                )
            )
        with pytest.raises(WorkspaceFilesystemError, match=r"regular|linked"):
            await workspace.read(
                WorkspaceReadRequest(
                    relative_path="linked.py",
                    expected_root_identity_sha256=identity.identity_sha256,
                    expected_mount_identity_sha256=mount_sha256,
                    permit=_permit(
                        identity.identity_sha256,
                        mount_sha256,
                        relative_path="linked.py",
                        offset=0,
                        maximum_bytes=32,
                    ),
                    offset=0,
                    maximum_bytes=32,
                )
            )
        with pytest.raises(WorkspaceFilesystemError):
            await workspace.read(
                WorkspaceReadRequest(
                    relative_path="source-link/main.py",
                    expected_root_identity_sha256=identity.identity_sha256,
                    expected_mount_identity_sha256=mount_sha256,
                    permit=_permit(
                        identity.identity_sha256,
                        mount_sha256,
                        relative_path="source-link/main.py",
                        offset=0,
                        maximum_bytes=32,
                    ),
                    offset=0,
                    maximum_bytes=32,
                )
            )
    finally:
        await workspace.close()


@pytest.mark.anyio
async def test_linux_workspace_rejects_forged_permit_and_stale_root_binding(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    (root / "file.txt").write_bytes(b"content")
    (root / "other.txt").write_bytes(b"other")
    workspace = _workspace(root)
    identity = await workspace.initialize()
    mount_sha256 = identity.mount.digest_sha256
    try:
        request = WorkspaceReadRequest(
            relative_path="file.txt",
            expected_root_identity_sha256=identity.identity_sha256,
            expected_mount_identity_sha256=mount_sha256,
            permit=replace(
                _permit(
                    identity.identity_sha256,
                    mount_sha256,
                    relative_path="file.txt",
                    offset=0,
                    maximum_bytes=8,
                ),
                workspace_id="another-workspace",
            ),
            offset=0,
            maximum_bytes=8,
        )
        with pytest.raises(WorkspaceFilesystemError, match="permit"):
            await workspace.read(request)
        replayed_request = replace(
            request,
            relative_path="other.txt",
            permit=_permit(
                identity.identity_sha256,
                mount_sha256,
                relative_path="file.txt",
                offset=0,
                maximum_bytes=8,
            ),
        )
        with pytest.raises(WorkspaceFilesystemError, match="permit"):
            await workspace.read(replayed_request)
        with pytest.raises(WorkspaceFilesystemError, match="binding"):
            await workspace.inspect(
                WorkspaceInspectRequest(
                    relative_path="file.txt",
                    expected_root_identity_sha256="c" * 64,
                    expected_mount_identity_sha256=mount_sha256,
                )
            )
    finally:
        await workspace.close()


@pytest.mark.anyio
async def test_linux_workspace_create_and_exact_write_are_durable_and_no_replace(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    workspace = _workspace(root)
    identity = await workspace.initialize()
    mount_sha256 = identity.mount.digest_sha256
    try:
        created = await workspace.create(
            WorkspaceCreateIntent(
                operation_id="operation-create",
                relative_path="new.txt",
                kind=WorkspaceObjectKind.REGULAR_FILE,
                content=b"first",
                mode=0o644,
                expected_root_identity_sha256=identity.identity_sha256,
                expected_mount_identity_sha256=mount_sha256,
            )
        )
        assert created.mutation_kind is WorkspaceMutationKind.CREATE
        assert created.content_sha256 == hashlib.sha256(b"first").hexdigest()
        assert created.staging_reference is not None
        assert not (root / created.staging_reference).exists()
        assert (root / "new.txt").read_bytes() == b"first"

        with pytest.raises(WorkspaceEffectNotStarted, match="target_exists"):
            await workspace.create(
                WorkspaceCreateIntent(
                    operation_id="operation-conflict",
                    relative_path="new.txt",
                    kind=WorkspaceObjectKind.REGULAR_FILE,
                    content=b"other",
                    mode=0o644,
                    expected_root_identity_sha256=identity.identity_sha256,
                    expected_mount_identity_sha256=mount_sha256,
                )
            )

        written = await workspace.write(
            WorkspaceWriteIntent(
                operation_id="operation-write",
                relative_path="new.txt",
                content=b"second",
                expected_object_version=created.object_version,
                expected_content_sha256=created.content_sha256 or "",
                expected_root_identity_sha256=identity.identity_sha256,
                expected_mount_identity_sha256=mount_sha256,
            )
        )
        assert written.mutation_kind is WorkspaceMutationKind.WRITE
        assert (root / "new.txt").read_bytes() == b"second"
        assert stat_mode(root / "new.txt") == 0o644

        with pytest.raises(WorkspaceEffectNotStarted, match="expected_state_changed"):
            await workspace.write(
                WorkspaceWriteIntent(
                    operation_id="operation-stale-write",
                    relative_path="new.txt",
                    content=b"third",
                    expected_object_version=created.object_version,
                    expected_content_sha256=created.content_sha256 or "",
                    expected_root_identity_sha256=identity.identity_sha256,
                    expected_mount_identity_sha256=mount_sha256,
                )
            )
        assert (root / "new.txt").read_bytes() == b"second"

        directory = await workspace.create(
            WorkspaceCreateIntent(
                operation_id="operation-directory",
                relative_path="package",
                kind=WorkspaceObjectKind.DIRECTORY,
                content=b"",
                mode=0o755,
                expected_root_identity_sha256=identity.identity_sha256,
                expected_mount_identity_sha256=mount_sha256,
            )
        )
        assert directory.object_identity.kind is WorkspaceObjectKind.DIRECTORY
        assert (root / "package").is_dir()
    finally:
        await workspace.close()


@pytest.mark.anyio
async def test_linux_workspace_staging_collision_is_retained_and_effect_does_not_start(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    workspace = _workspace(root)
    identity = await workspace.initialize()
    mount_sha256 = identity.mount.digest_sha256
    staging = workspace.staging_reference(
        operation_id="operation-collision",
        mutation_kind=WorkspaceMutationKind.CREATE,
        relative_path="target.txt",
    )
    (root / staging).write_bytes(b"retained-foreign-entry")
    try:
        with pytest.raises(WorkspaceEffectNotStarted, match="staging_collision"):
            await workspace.create(
                WorkspaceCreateIntent(
                    operation_id="operation-collision",
                    relative_path="target.txt",
                    kind=WorkspaceObjectKind.REGULAR_FILE,
                    content=b"new",
                    mode=0o644,
                    expected_root_identity_sha256=identity.identity_sha256,
                    expected_mount_identity_sha256=mount_sha256,
                )
            )
        assert not (root / "target.txt").exists()
        assert (root / staging).read_bytes() == b"retained-foreign-entry"
    finally:
        await workspace.close()


@pytest.mark.anyio
async def test_linux_workspace_post_publish_durability_failure_is_uncertain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    workspace = _workspace(root)
    identity = await workspace.initialize()
    mount_sha256 = identity.mount.digest_sha256
    root_inode = root.stat().st_ino
    original_fsync = os.fsync

    def fail_parent_fsync(descriptor: int) -> None:
        if os.fstat(descriptor).st_ino == root_inode:
            raise OSError("injected parent fsync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_parent_fsync)
    try:
        with pytest.raises(WorkspaceEffectUncertain, match="uncertain"):
            await workspace.create(
                WorkspaceCreateIntent(
                    operation_id="operation-uncertain",
                    relative_path="maybe.txt",
                    kind=WorkspaceObjectKind.REGULAR_FILE,
                    content=b"published-before-fsync",
                    mode=0o644,
                    expected_root_identity_sha256=identity.identity_sha256,
                    expected_mount_identity_sha256=mount_sha256,
                )
            )
        assert (root / "maybe.txt").read_bytes() == b"published-before-fsync"
    finally:
        await workspace.close()


@pytest.mark.anyio
async def test_linux_workspace_fails_closed_on_missing_or_changed_mount_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    unavailable = _workspace(root, proc_root=tmp_path / "missing-proc")
    with pytest.raises(WorkspaceFilesystemError, match="mount evidence"):
        await unavailable.initialize()

    (root / "nested").mkdir()
    workspace = _workspace(root)
    await workspace.initialize()
    original = workspace._mount_identity_for_fd
    nested_inode = (root / "nested").stat().st_ino

    def substituted_mount(descriptor: int) -> MountIdentity:
        observed = original(descriptor)
        if os.fstat(descriptor).st_ino != nested_inode:
            return observed
        return MountIdentity(
            mount_id=observed.mount_id + 1,
            device=observed.device,
            filesystem_type=observed.filesystem_type,
            digest_sha256=canonical_sha256(
                {
                    "device": observed.device,
                    "filesystem_type": observed.filesystem_type,
                    "mount_id": observed.mount_id + 1,
                }
            ),
        )

    monkeypatch.setattr(workspace, "_mount_identity_for_fd", substituted_mount)
    try:
        with pytest.raises(WorkspaceFilesystemError, match=r"crossed.*mount"):
            await workspace.verify_scope_no_submounts("")
    finally:
        await workspace.close()


@pytest.mark.anyio
async def test_linux_workspace_keeps_deferred_effects_explicitly_unavailable(
    tmp_path: Path,
) -> None:
    workspace = _workspace(_root(tmp_path))
    await workspace.initialize()
    try:
        with pytest.raises(WorkspaceCapabilityUnavailable, match="search"):
            await workspace.search(object())
        with pytest.raises(WorkspaceCapabilityUnavailable, match="move"):
            await workspace.move(object())
        with pytest.raises(WorkspaceCapabilityUnavailable, match="delete"):
            await workspace.delete(object())
    finally:
        await workspace.close()


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o7777
