"""P2.8 descriptor-anchored source reads: deterministic I/O failure handling.

These fixtures only use disposable in-root files and simulated OS failures.
Real symlink adversarial and OS sandbox acceptance are separate P3 gates.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from binnacle.features.development_intelligence import lsp_workspace_access as access
from binnacle.features.development_intelligence.lsp_workspace_access import (
    AuthorizedWorkspace,
    WorkspaceAccessError,
    WorkspaceStaleError,
)


@pytest.fixture
def source_tree(tmp_path):
    authority = (tmp_path / "approved").resolve()
    project = authority / "source-project"
    package = project / "pkg"
    package.mkdir(parents=True)
    (project / ".git").write_text("gitdir: ../metadata/worktrees/source-project\n")
    source = package / "good.py"
    source.write_text("value = 'safe'\n", encoding="utf-8")
    return authority, project, source


@pytest.mark.parametrize(
    "path",
    [
        None,
        17,
        [],
        "relative.py",
        "",
        "/absolute/./a.py",
        "/absolute/x/../a.py",
        "/absolute//a.py",
        "/bad\x00name.py",
    ],
)
def test_invalid_path_components_are_rejected_without_open(path):
    with pytest.raises(WorkspaceAccessError, match="invalid_workspace_path"):
        access._components(path, absolute=True)


@pytest.mark.parametrize(
    "extensions",
    [
        (),
        [".py"],
        ("",),
        ("py",),
        (".bad-file",),
        (12,),
    ],
)
def test_unsafe_extension_configuration_rejected(source_tree, extensions):
    authority, _project, source = source_tree
    with pytest.raises(ValueError, match="invalid_source_file_extensions"):
        AuthorizedWorkspace((authority,), source, allowed_suffixes=extensions)


def test_host_root_file_and_wrong_source_are_refused(source_tree):
    authority, project, source = source_tree
    with pytest.raises(WorkspaceAccessError, match="not_directory"):
        AuthorizedWorkspace((source,), source)
    with pytest.raises(WorkspaceAccessError, match="outside_allowed_roots"):
        AuthorizedWorkspace((authority,), authority)
    with pytest.raises(WorkspaceAccessError, match="source_directory_unauthorized"):
        AuthorizedWorkspace((authority,), source).snapshot("pkg/missing-dir/other.py")
    with pytest.raises(WorkspaceAccessError, match="source_not_authorized"):
        AuthorizedWorkspace((authority,), source).snapshot("pkg/not-existing.py")
    with pytest.raises(WorkspaceAccessError, match="source_not_regular_file"):
        (project / "pkg" / "directory.py").mkdir()
        AuthorizedWorkspace((authority,), source).snapshot("pkg/directory.py")


def test_nested_operator_roots_prefer_longer_prefix(source_tree):
    authority, project, source = source_tree
    parent_root = AuthorizedWorkspace((authority,), source)
    direct_root = AuthorizedWorkspace((authority, project), source)
    assert parent_root.workspace_root == project
    assert direct_root.workspace_root == project
    assert direct_root.snapshot(direct_root.source_file).contents == "value = 'safe'\n"


def test_marker_discovery_refuses_stat_failure(source_tree, monkeypatch):
    authority, _project, source = source_tree
    original = os.stat

    def fail_marker(path, *args, **kwargs):
        if path == ".git" and kwargs.get("dir_fd") is not None:
            raise PermissionError(errno.EACCES, "denied")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(access.os, "stat", fail_marker)
        with pytest.raises(WorkspaceAccessError, match="workspace_marker_unavailable"):
            AuthorizedWorkspace((authority,), source)


def test_operator_root_disappears_before_admission(source_tree, monkeypatch):
    authority, _project, source = source_tree
    original = Path.resolve

    def fail_configured_root(path, *args, **kwargs):
        if path == authority:
            raise FileNotFoundError(errno.ENOENT, "unavailable")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "resolve", fail_configured_root)
        with pytest.raises(
            WorkspaceAccessError, match="configured_workspace_root_unavailable"
        ):
            AuthorizedWorkspace((authority,), source)


def test_read_syscall_failure_is_sanitized(source_tree, monkeypatch):
    authority, _project, source = source_tree
    workspace = AuthorizedWorkspace((authority,), source)
    original = os.read

    def broken_read(fd, n):
        if n <= 64 * 1024:
            raise OSError(errno.EIO, "sensitive kernel detail")
        return original(fd, n)

    with monkeypatch.context() as scoped:
        scoped.setattr(access.os, "read", broken_read)
        with pytest.raises(
            WorkspaceAccessError, match="source_read_unavailable"
        ) as exc:
            workspace.snapshot("pkg/good.py")
    assert "sensitive kernel" not in str(exc.value)


@pytest.mark.parametrize(
    "stat_call,kind",
    [
        (2, "source_stat_unavailable"),
        (3, "source_stat_changed_during_read"),
    ],
)
def test_before_or_after_read_fstat_error_is_fail_closed(
    source_tree, monkeypatch, stat_call, kind
):
    authority, _project, source = source_tree
    workspace = AuthorizedWorkspace((authority,), source)
    real_fstat = os.fstat
    calls = 0

    def fail_one_stat(fd):
        nonlocal calls
        calls += 1
        if calls == stat_call:
            raise OSError(errno.EIO, "sensitive OS detail")
        return real_fstat(fd)

    with monkeypatch.context() as scoped:
        scoped.setattr(access.os, "fstat", fail_one_stat)
        expected = WorkspaceStaleError if stat_call == 3 else WorkspaceAccessError
        with pytest.raises(expected, match=kind):
            workspace.snapshot("pkg/good.py")


def test_source_changed_between_file_stats_is_not_returned(source_tree, monkeypatch):
    authority, _project, source = source_tree
    workspace = AuthorizedWorkspace((authority,), source)
    original = os.read
    changed = False

    def changing_read(fd, n):
        nonlocal changed
        block = original(fd, n)
        if not changed:
            changed = True
            source.write_text("value = 'modified'\n")
        return block

    with monkeypatch.context() as scoped:
        scoped.setattr(access.os, "read", changing_read)
        with pytest.raises(WorkspaceStaleError, match="source_modified_during_read"):
            workspace.snapshot("pkg/good.py")


def test_source_lost_after_read_is_not_returned(source_tree, monkeypatch):
    authority, _project, source = source_tree
    workspace = AuthorizedWorkspace((authority,), source)
    original = os.stat

    def vanish_after_read(path, *args, **kwargs):
        if path == "good.py" and kwargs.get("dir_fd") is not None:
            raise FileNotFoundError(errno.ENOENT, "lost")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(access.os, "stat", vanish_after_read)
        with pytest.raises(WorkspaceStaleError, match="source_replaced_during_read"):
            workspace.snapshot("pkg/good.py")


def test_root_identity_stat_failure_releases_descriptor(source_tree, monkeypatch):
    authority, _project, source = source_tree
    workspace = AuthorizedWorkspace((authority,), source)

    def unavailable(_fd):
        raise OSError(errno.EIO, "not available")

    with monkeypatch.context() as scoped:
        scoped.setattr(access.os, "fstat", unavailable)
        with pytest.raises(WorkspaceAccessError, match="workspace_root_unavailable"):
            workspace.snapshot("pkg/good.py")
    assert workspace.snapshot("pkg/good.py").contents == "value = 'safe'\n"


def test_missing_source_or_wrong_suffix_becomes_stale_snapshot(source_tree):
    authority, _project, source = source_tree
    workspace = AuthorizedWorkspace((authority,), source)
    first = workspace.snapshot("pkg/good.py")
    source.unlink()
    with pytest.raises(WorkspaceStaleError, match="source_no_longer_authorized"):
        workspace.assert_fresh(first)


@pytest.mark.parametrize(
    "value",
    [
        12,
        None,
        [],
        "data:text/plain,a",
        "https://domain.test/a.py",
        "file:///tmp/source.py?rev=2",
        "file:///tmp/source.py#part",
        "file://untrusted-host.local/tmp/source.py",
        "file:relative.py",
    ],
)
def test_invalid_result_uris_are_never_opened(source_tree, value):
    authority, _project, source = source_tree
    workspace = AuthorizedWorkspace((authority,), source)
    with pytest.raises(
        WorkspaceAccessError, match="(invalid_result_uri|outside_workspace)"
    ):
        workspace.snapshot_uri(value)


def test_source_ceiling_and_non_utf8_rejected_without_returns(source_tree):
    authority, project, source = source_tree
    ws = AuthorizedWorkspace((authority,), source, max_file_bytes=64)
    assert ws.root_identity == (
        source.parent.parent.stat().st_dev,
        source.parent.parent.stat().st_ino,
    )
    large = project / "pkg" / "long.py"
    large.write_text("a" * 65)
    with pytest.raises(WorkspaceAccessError, match="source_too_large"):
        ws.snapshot("pkg/long.py")
    no_text = project / "pkg" / "not-text.py"
    no_text.write_bytes(b"value=\xff\n")
    with pytest.raises(WorkspaceAccessError, match="source_not_utf8"):
        ws.snapshot("pkg/not-text.py")
    no_text.write_bytes(b"value=\x00\n")
    with pytest.raises(WorkspaceAccessError, match="binary_source_unsupported"):
        ws.snapshot("pkg/not-text.py")


def test_unsupported_byte_limits_and_cross_workspace_uri_are_denied(source_tree):
    authority, _project, source = source_tree
    for size in (0, -1, True, access.MAX_SOURCE_BYTES + 1):
        with pytest.raises(ValueError, match="invalid_workspace_file_ceiling"):
            AuthorizedWorkspace((authority,), source, max_file_bytes=size)
    ws = AuthorizedWorkspace((authority,), source)
    external = authority / "other.py"
    external.write_text("x = 1\n")
    with pytest.raises(WorkspaceAccessError, match="result_outside_workspace"):
        ws.snapshot_uri(external.as_uri())
    assert ws.snapshot_uri(source.as_uri()).relative_path == "pkg/good.py"
