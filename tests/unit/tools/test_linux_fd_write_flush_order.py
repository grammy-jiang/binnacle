"""Regression for SEC-FU-14: flush final permissions after successful revalidation.

All filesystem mutations are confined to pytest temporary roots; no production
files or services are accessed. Linux-specific behavior is pinned per test.
"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
import sys

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import RootsSettings
from binnacle.features.files import fd_write
from binnacle.features.files.tools import write_file

LINUX_ONLY = pytest.mark.skipif(sys.platform != "linux", reason="Linux FD write")


@pytest.fixture
def allowed(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    return root


@LINUX_ONLY
@pytest.mark.parametrize("edit", [False, True])
def test_revalidated_overwrite_flushes_final_mode_before_publish(
    allowed, monkeypatch, edit
):
    """Existing-mode metadata must be durable at the same flush as the bytes."""
    target = allowed / "target"
    target.write_bytes(b"before")
    target.chmod(0o664)

    actual_chmod = fd_write.os.fchmod
    actual_fsync = fd_write.os.fsync
    actual_replace = fd_write.os.replace
    actual_verify = fd_write._verify_parent
    events = []

    def chmod(fd, mode):
        events.append("fchmod")
        return actual_chmod(fd, mode)

    def fsync(fd):
        events.append(("fsync", stat.S_IMODE(os.fstat(fd).st_mode)))
        return actual_fsync(fd)

    def check_parent(fd, path, tool):
        if "fchmod" in events:
            events.append("parent-check")
        return actual_verify(fd, path, tool)

    def replace(*args, **kwargs):
        events.append("rename")
        return actual_replace(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(fd_write, "_verify_parent", check_parent)
        patch.setattr(fd_write.os, "fchmod", chmod)
        patch.setattr(fd_write.os, "fsync", fsync)
        patch.setattr(fd_write.os, "replace", replace)
        kwargs = {}
        if edit:
            before = target.stat()
            kwargs["expected_sha256"] = hashlib.sha256(b"before").hexdigest()
            kwargs["expected_identity"] = (before.st_dev, before.st_ino)
        receipt = fd_write.write_bytes(
            target, (allowed,), b"after", create_parents=False, **kwargs
        )

    assert events == ["fchmod", ("fsync", 0o664), "parent-check", "rename"]
    assert receipt.action == "overwritten"
    assert target.read_bytes() == b"after"
    assert stat.S_IMODE(target.stat().st_mode) == 0o664
    assert not list(allowed.glob(".binnacle-write-*"))


@LINUX_ONLY
def test_conflict_refuses_without_syncing_a_discarded_sibling(allowed, monkeypatch):
    """A loser should not fsync an inode it has decided not to publish."""
    target = allowed / "target"
    target.write_bytes(b"before")
    original_write = fd_write.os.write
    original_fsync = fd_write.os.fsync
    synchronizations = []
    raced = False

    def write(fd, data):
        nonlocal raced
        result = original_write(fd, data)
        if not raced:
            raced = True
            target.write_bytes(b"other-writer")
        return result

    def fsync(fd):
        synchronizations.append(fd)
        return original_fsync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(fd_write.os, "write", write)
        patch.setattr(fd_write.os, "fsync", fsync)
        with pytest.raises(ToolError, match="changed"):
            fd_write.write_bytes(target, (allowed,), b"ours", create_parents=False)

    assert raced
    assert synchronizations == []
    assert target.read_bytes() == b"other-writer"
    assert not list(allowed.glob(".binnacle-write-*"))


@LINUX_ONLY
def test_failed_mode_change_never_syncs_or_publishes(allowed, monkeypatch):
    target = allowed / "target"
    target.write_bytes(b"before")
    original_fsync = fd_write.os.fsync
    sync_count = 0

    def fsync(fd):
        nonlocal sync_count
        sync_count += 1
        return original_fsync(fd)

    def fail_mode_change(_fd, _mode):
        raise OSError(errno.EIO, "injected chmod failure")

    with monkeypatch.context() as patch:
        patch.setattr(fd_write.os, "fchmod", fail_mode_change)
        patch.setattr(fd_write.os, "fsync", fsync)
        with pytest.raises(OSError, match="injected chmod failure"):
            fd_write.write_bytes(target, (allowed,), b"after", create_parents=False)

    assert sync_count == 0
    assert target.read_bytes() == b"before"
    assert not list(allowed.glob(".binnacle-write-*"))


@LINUX_ONLY
def test_new_file_flushes_data_once_without_mode_change(allowed, monkeypatch):
    target = allowed / "new"
    actual_fsync = fd_write.os.fsync
    actual_replace = fd_write.os.replace
    events = []

    def fsync(fd):
        events.append("fsync")
        return actual_fsync(fd)

    def replace(*args, **kwargs):
        events.append("rename")
        return actual_replace(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(fd_write.os, "fsync", fsync)
        patch.setattr(fd_write.os, "replace", replace)
        fd_write.write_bytes(target, (allowed,), b"new", create_parents=False)

    assert events == ["fsync", "rename"]
    assert target.read_bytes() == b"new"


@LINUX_ONLY
def test_parent_retarget_during_fsync_is_refused_before_rename(
    allowed, tmp_path, monkeypatch
):
    """A moved parent after the slow sync must be rechecked before publish."""
    parent = allowed / "parent"
    parent.mkdir()
    target = parent / "target"
    target.write_bytes(b"before")
    moved = tmp_path / "moved"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "target").write_bytes(b"outside")
    actual_fsync = fd_write.os.fsync
    raced = False

    def relocate_during_sync(fd):
        nonlocal raced
        if not raced:
            raced = True
            parent.rename(moved)
            parent.symlink_to(outside, target_is_directory=True)
        return actual_fsync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(fd_write.os, "fsync", relocate_during_sync)
        with pytest.raises(ToolError, match="changed"):
            fd_write.write_bytes(target, (allowed,), b"ours", create_parents=False)

    assert raced
    assert (moved / "target").read_bytes() == b"before"
    assert (outside / "target").read_bytes() == b"outside"
    assert not list(moved.glob(".binnacle-write-*"))


def test_non_linux_write_dispatch_keeps_path_fallback(tmp_path, monkeypatch):
    """This executes on macOS too, so the module is not all-skipped there."""
    root = tmp_path / "allowed"
    root.mkdir()
    roots = RootsSettings(default_root=root, extra_roots=())

    def forbidden_fd_write(*_args, **_kwargs):
        raise AssertionError("Linux descriptor backend invoked on Darwin")

    with monkeypatch.context() as patch:
        patch.setattr(write_file.sys, "platform", "darwin")
        patch.setattr(fd_write, "write_bytes", forbidden_fd_write)
        result = write_file.write_file_impl(
            str(root / "new.txt"), "hello", roots=roots
        ).structured_content

    assert result["action"] == "created"
    assert (root / "new.txt").read_text() == "hello"
