"""Adversarial unit coverage for the Linux workspace security boundary."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
from pathlib import Path

import pytest

from binnacle.adapters.workspace import (
    LinuxWorkspace,
    WorkspaceEffectNotStarted,
    WorkspaceEffectUncertain,
    WorkspaceFilesystemError,
)
from binnacle.domain.workspace import (
    ContentReadPermit,
    WorkspaceObjectKind,
    WorkspaceRootIdentity,
    canonical_sha256,
)
from binnacle.ports.workspace import (
    WorkspaceCreateIntent,
    WorkspaceEntry,
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


def _root(tmp_path: Path, name: str = "workspace") -> Path:
    root = tmp_path / name
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    return root


def _workspace(root: Path, **overrides: object) -> LinuxWorkspace:
    return LinuxWorkspace(
        root=root,
        workspace_id="binnacle-source",
        profile_sha256=PROFILE_SHA256,
        **overrides,  # type: ignore[arg-type]
    )


def _request_sha256(
    *,
    relative_path: str,
    offset: int,
    maximum_bytes: int,
    session_id: str = "session-fixture",
) -> str:
    return canonical_sha256(
        {
            "maximum_bytes": maximum_bytes,
            "offset": offset,
            "relative_path": relative_path,
            "session_id": session_id,
            "workspace_id": "binnacle-source",
        }
    )


def _permit(
    identity: WorkspaceRootIdentity,
    *,
    relative_path: str,
    offset: int,
    maximum_bytes: int,
) -> ContentReadPermit:
    return ContentReadPermit(
        permit_id="permit-fixture",
        session_id="session-fixture",
        session_state_version=1,
        workspace_id=identity.workspace_id,
        workspace_profile_sha256=identity.profile_sha256,
        root_identity_sha256=identity.identity_sha256,
        mount_identity_sha256=identity.mount.digest_sha256,
        request_sha256=_request_sha256(
            relative_path=relative_path,
            offset=offset,
            maximum_bytes=maximum_bytes,
        ),
        content_guard_epoch=1,
    )


def _read_request(
    identity: WorkspaceRootIdentity,
    *,
    relative_path: str,
    offset: int,
    maximum_bytes: int,
) -> WorkspaceReadRequest:
    return WorkspaceReadRequest(
        relative_path=relative_path,
        expected_root_identity_sha256=identity.identity_sha256,
        expected_mount_identity_sha256=identity.mount.digest_sha256,
        permit=_permit(
            identity,
            relative_path=relative_path,
            offset=offset,
            maximum_bytes=maximum_bytes,
        ),
        offset=offset,
        maximum_bytes=maximum_bytes,
    )


async def _inspect_file(
    workspace: LinuxWorkspace,
    identity: WorkspaceRootIdentity,
    relative_path: str,
) -> WorkspaceEntry:
    return await workspace.inspect(
        WorkspaceInspectRequest(
            relative_path=relative_path,
            expected_root_identity_sha256=identity.identity_sha256,
            expected_mount_identity_sha256=identity.mount.digest_sha256,
            include_content_digest=True,
            maximum_hash_bytes=1024,
        )
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"maximum_mutation_bytes": 0},
        {"maximum_read_bytes": 0},
        {"maximum_list_entries": 0},
        {"maximum_list_entries": 2, "maximum_preflight_entries": 1},
    ],
)
def test_linux_workspace_rejects_unsafe_resource_bounds(
    tmp_path: Path,
    overrides: dict[str, int],
) -> None:
    with pytest.raises(ValueError, match=r"bound|limit|too small"):
        _workspace(_root(tmp_path), **overrides)


@pytest.mark.anyio
async def test_linux_workspace_rejects_uninitialized_unsafe_and_symlink_roots(
    tmp_path: Path,
) -> None:
    uninitialized = _workspace(_root(tmp_path, "uninitialized"))
    with pytest.raises(WorkspaceFilesystemError, match="not initialized"):
        await uninitialized.root_identity()

    unsafe = _root(tmp_path, "unsafe")
    unsafe.chmod(0o770)
    with pytest.raises(WorkspaceFilesystemError, match=r"ownership|permissions"):
        await _workspace(unsafe).initialize()

    target = _root(tmp_path, "target")
    symlink = tmp_path / "symlink-root"
    symlink.symlink_to(target, target_is_directory=True)
    with pytest.raises(WorkspaceFilesystemError, match="opened safely"):
        await _workspace(symlink).initialize()


@pytest.mark.anyio
async def test_linux_workspace_preflight_bounds_depth_and_entry_count(
    tmp_path: Path,
) -> None:
    entry_root = _root(tmp_path, "entry-bound")
    (entry_root / "one").write_bytes(b"1")
    (entry_root / "two").write_bytes(b"2")
    entry_bounded = _workspace(
        entry_root,
        maximum_list_entries=1,
        maximum_preflight_entries=1,
    )
    with pytest.raises(WorkspaceFilesystemError, match="enumeration exceeded"):
        await entry_bounded.initialize()

    depth_root = _root(tmp_path, "depth-bound")
    current = depth_root
    for index in range(65):
        current = current / f"d{index}"
        current.mkdir()
    with pytest.raises(WorkspaceFilesystemError, match="depth exceeded"):
        await _workspace(depth_root).initialize()


@pytest.mark.anyio
async def test_linux_workspace_bounded_listing_and_large_file_chunks(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    nested = root / "nested"
    nested.mkdir()
    for name in ("a", "b", "c"):
        (nested / name).write_bytes(name.encode())
    (root / "large.bin").write_bytes(b"0123456789")
    workspace = _workspace(
        root,
        maximum_mutation_bytes=4,
        maximum_read_bytes=4,
        maximum_list_entries=2,
    )
    identity = await workspace.initialize()
    try:
        listing = await workspace.list(
            WorkspaceListRequest(
                relative_path="nested",
                expected_root_identity_sha256=identity.identity_sha256,
                expected_mount_identity_sha256=identity.mount.digest_sha256,
                maximum_entries=2,
            )
        )
        assert len(listing.entries) == 2
        assert listing.truncated

        with pytest.raises(WorkspaceFilesystemError, match="listing bound"):
            await workspace.list(
                WorkspaceListRequest(
                    relative_path="nested",
                    expected_root_identity_sha256=identity.identity_sha256,
                    expected_mount_identity_sha256=identity.mount.digest_sha256,
                    maximum_entries=0,
                )
            )

        await workspace.verify_scope_no_submounts("large.bin")
        chunk = await workspace.read(
            _read_request(
                identity,
                relative_path="large.bin",
                offset=0,
                maximum_bytes=4,
            )
        )
        assert chunk.content == b"0123"
        assert chunk.next_offset == 4
        assert not chunk.complete
        assert chunk.content_sha256 is None

        with pytest.raises(WorkspaceFilesystemError, match="offset"):
            await workspace.read(
                _read_request(
                    identity,
                    relative_path="large.bin",
                    offset=11,
                    maximum_bytes=4,
                )
            )
        with pytest.raises(WorkspaceFilesystemError, match="range"):
            await workspace.read(
                _read_request(
                    identity,
                    relative_path="large.bin",
                    offset=0,
                    maximum_bytes=0,
                )
            )
    finally:
        await workspace.close()


@pytest.mark.anyio
async def test_linux_workspace_rejects_special_and_nonregular_content(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    special = root / "special"
    special.write_bytes(b"special")
    special.chmod(0o4755)
    fifo = root / "pipe"
    os.mkfifo(fifo)
    workspace = _workspace(root)
    identity = await workspace.initialize()
    try:
        inspected = await workspace.inspect(
            WorkspaceInspectRequest(
                relative_path="pipe",
                expected_root_identity_sha256=identity.identity_sha256,
                expected_mount_identity_sha256=identity.mount.digest_sha256,
            )
        )
        assert inspected.kind is WorkspaceObjectKind.OTHER
        for relative_path, match in (("special", "special mode"), ("pipe", "regular file")):
            with pytest.raises(WorkspaceFilesystemError, match=match):
                await workspace.read(
                    _read_request(
                        identity,
                        relative_path=relative_path,
                        offset=0,
                        maximum_bytes=8,
                    )
                )
    finally:
        await workspace.close()


@pytest.mark.anyio
async def test_linux_workspace_maps_create_preconditions_to_zero_start(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    workspace = _workspace(root, maximum_mutation_bytes=4)
    identity = await workspace.initialize()

    def intent(
        *,
        operation_id: str,
        kind: WorkspaceObjectKind = WorkspaceObjectKind.REGULAR_FILE,
        content: bytes = b"x",
        mode: int = 0o644,
        relative_path: str = "target",
        root_sha256: str = identity.identity_sha256,
    ) -> WorkspaceCreateIntent:
        return WorkspaceCreateIntent(
            operation_id=operation_id,
            relative_path=relative_path,
            kind=kind,
            content=content,
            mode=mode,
            expected_root_identity_sha256=root_sha256,
            expected_mount_identity_sha256=identity.mount.digest_sha256,
        )

    cases = (
        intent(operation_id="bad-mode", mode=0o666),
        intent(
            operation_id="bad-directory",
            kind=WorkspaceObjectKind.DIRECTORY,
            content=b"not-empty",
            mode=0o755,
        ),
        intent(operation_id="bad-kind", kind=WorkspaceObjectKind.SYMLINK),
        intent(operation_id="too-large", content=b"12345"),
        intent(operation_id="stale-root", root_sha256="b" * 64),
        intent(operation_id="missing-parent", relative_path="missing/target"),
    )
    try:
        for candidate in cases:
            with pytest.raises(WorkspaceEffectNotStarted):
                await workspace.create(candidate)
        assert list(root.iterdir()) == []
    finally:
        await workspace.close()


@pytest.mark.anyio
async def test_linux_workspace_write_rejects_unsupported_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    target = root / "target"
    target.write_bytes(b"old")
    workspace = _workspace(root)
    identity = await workspace.initialize()

    async def write_from_current(operation_id: str) -> None:
        current = await _inspect_file(workspace, identity, "target")
        await workspace.write(
            WorkspaceWriteIntent(
                operation_id=operation_id,
                relative_path="target",
                content=b"new",
                expected_object_version=current.object_version,
                expected_content_sha256=current.object_identity.content_sha256 or "",
                expected_root_identity_sha256=identity.identity_sha256,
                expected_mount_identity_sha256=identity.mount.digest_sha256,
            )
        )

    supported_listxattr = os.listxattr
    try:
        target.chmod(0o666)
        with pytest.raises(WorkspaceEffectNotStarted, match="metadata_unsupported"):
            await write_from_current("wrong-mode")

        target.chmod(0o644)

        def target_xattrs(descriptor: int) -> list[str]:
            if os.fstat(descriptor).st_ino == target.stat().st_ino:
                return ["security.capability"]
            return supported_listxattr(descriptor)

        monkeypatch.setattr(os, "listxattr", target_xattrs)
        with pytest.raises(WorkspaceEffectNotStarted, match="xattrs_unsupported"):
            await write_from_current("has-xattr")

        def unavailable_xattrs(descriptor: int) -> list[str]:
            if os.fstat(descriptor).st_ino == target.stat().st_ino:
                raise OSError("xattrs unavailable")
            return supported_listxattr(descriptor)

        monkeypatch.setattr(os, "listxattr", unavailable_xattrs)
        with pytest.raises(WorkspaceEffectNotStarted, match="xattr_check_unavailable"):
            await write_from_current("xattr-unavailable")

        monkeypatch.setattr(os, "listxattr", supported_listxattr)
        (root / "alias").hardlink_to(target)
        with pytest.raises(WorkspaceEffectNotStarted, match="not_started"):
            await workspace.write(
                WorkspaceWriteIntent(
                    operation_id="multiply-linked",
                    relative_path="target",
                    content=b"new",
                    expected_object_version="b" * 64,
                    expected_content_sha256=hashlib.sha256(b"old").hexdigest(),
                    expected_root_identity_sha256=identity.identity_sha256,
                    expected_mount_identity_sha256=identity.mount.digest_sha256,
                )
            )
        assert target.read_bytes() == b"old"
    finally:
        await workspace.close()


@pytest.mark.anyio
@pytest.mark.parametrize("mutation", ["directory", "write"])
async def test_linux_workspace_parent_fsync_failure_after_effect_is_uncertain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    root = _root(tmp_path)
    target = root / "target"
    target.write_bytes(b"old")
    workspace = _workspace(root)
    identity = await workspace.initialize()
    current = await _inspect_file(workspace, identity, "target")
    root_inode = root.stat().st_ino
    real_fsync = os.fsync

    def fail_parent(descriptor: int) -> None:
        if os.fstat(descriptor).st_ino == root_inode:
            raise OSError("injected parent fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_parent)
    try:
        with pytest.raises(WorkspaceEffectUncertain, match="uncertain"):
            if mutation == "directory":
                await workspace.create(
                    WorkspaceCreateIntent(
                        operation_id="uncertain-directory",
                        relative_path="directory",
                        kind=WorkspaceObjectKind.DIRECTORY,
                        content=b"",
                        mode=0o755,
                        expected_root_identity_sha256=identity.identity_sha256,
                        expected_mount_identity_sha256=identity.mount.digest_sha256,
                    )
                )
            else:
                await workspace.write(
                    WorkspaceWriteIntent(
                        operation_id="uncertain-write",
                        relative_path="target",
                        content=b"new",
                        expected_object_version=current.object_version,
                        expected_content_sha256=current.object_identity.content_sha256 or "",
                        expected_root_identity_sha256=identity.identity_sha256,
                        expected_mount_identity_sha256=identity.mount.digest_sha256,
                    )
                )
    finally:
        await workspace.close()


def _proc_workspace(tmp_path: Path) -> tuple[LinuxWorkspace, Path]:
    proc_root = tmp_path / "proc"
    (proc_root / "self" / "fdinfo").mkdir(parents=True)
    workspace = _workspace(_root(tmp_path), proc_root=proc_root)
    return workspace, proc_root


@pytest.mark.parametrize(
    ("content", "match"),
    [
        (b"broken\n", "malformed record"),
        (b"x 0 0:1 / / - ext4 / rw\n", "mount ID is malformed"),
        (b"7 0 nope / / - ext4 / rw\n", "facts are malformed"),
        (b"7 0 0:1 / / - " + b"x" * 65 + b" / rw\n", "facts are unsafe"),
        (b"8 0 0:1 / / - ext4 / rw\n", "not unique"),
    ],
)
def test_linux_workspace_mountinfo_parser_fails_closed(
    tmp_path: Path,
    content: bytes,
    match: str,
) -> None:
    workspace, proc_root = _proc_workspace(tmp_path)
    (proc_root / "self" / "mountinfo").write_bytes(content)
    with pytest.raises(WorkspaceFilesystemError, match=match):
        workspace._mountinfo_facts(7)


@pytest.mark.parametrize("content", [b"mnt_id:\tbad\n", b"mnt_id:\t7\nmnt_id:\t8\n"])
def test_linux_workspace_fdinfo_parser_fails_closed(
    tmp_path: Path,
    content: bytes,
) -> None:
    workspace, proc_root = _proc_workspace(tmp_path)
    descriptor = 123
    (proc_root / "self" / "fdinfo" / str(descriptor)).write_bytes(content)
    with pytest.raises(WorkspaceFilesystemError, match="mount ID"):
        workspace._mount_id_for_fd(descriptor)


def test_linux_workspace_proc_evidence_is_regular_and_bounded(tmp_path: Path) -> None:
    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(WorkspaceFilesystemError, match="unsafe"):
        LinuxWorkspace._read_proc_file(directory, maximum_bytes=8)

    oversized = tmp_path / "oversized"
    oversized.write_bytes(b"123456789")
    with pytest.raises(WorkspaceFilesystemError, match="unbounded"):
        LinuxWorkspace._read_proc_file(oversized, maximum_bytes=8)


def test_linux_workspace_rejects_mount_device_disagreement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    workspace = _workspace(root)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    observed_device = os.fstat(descriptor).st_dev
    monkeypatch.setattr(workspace, "_mount_id_for_fd", lambda _descriptor: 7)
    monkeypatch.setattr(
        workspace,
        "_mountinfo_facts",
        lambda _mount_id: ("ext4", observed_device + 1),
    )
    try:
        with pytest.raises(WorkspaceFilesystemError, match="device disagree"):
            workspace._mount_identity_for_fd(descriptor)
    finally:
        os.close(descriptor)


class _FakeRename:
    argtypes: object = None
    restype: object = None

    def __init__(self, result: int) -> None:
        self._result = result

    def __call__(self, *_arguments: object) -> int:
        return self._result


class _FakeLibc:
    def __init__(self, result: int) -> None:
        self.renameat2 = _FakeRename(result)


@pytest.mark.parametrize(
    ("error", "exception"),
    [(errno.EEXIST, FileExistsError), (errno.ENOSYS, OSError)],
)
def test_linux_workspace_rename_noreplace_maps_kernel_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: int,
    exception: type[OSError],
) -> None:
    def fake_cdll(*_arguments: object, **_keywords: object) -> _FakeLibc:
        return _FakeLibc(-1)

    monkeypatch.setattr(ctypes, "CDLL", fake_cdll)
    monkeypatch.setattr(ctypes, "get_errno", lambda: error)
    with pytest.raises(exception):
        LinuxWorkspace._rename_noreplace(1, "source", 1, "target")


def test_linux_workspace_rename_and_write_primitives_fail_closed_when_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_rename(*_arguments: object, **_keywords: object) -> object:
        return object()

    monkeypatch.setattr(ctypes, "CDLL", no_rename)
    with pytest.raises(WorkspaceEffectNotStarted, match="unavailable"):
        LinuxWorkspace._rename_noreplace(1, "source", 1, "target")

    path = tmp_path / "target"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    monkeypatch.setattr(os, "write", lambda _descriptor, _content: 0)
    try:
        with pytest.raises(OSError, match="short"):
            LinuxWorkspace._write_all(descriptor, b"content")
    finally:
        os.close(descriptor)
