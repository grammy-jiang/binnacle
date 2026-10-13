"""SEC-FU-14 deterministic fixtures: FD-relative Linux write/edit boundaries.

Only tmp_path trees are manipulated; never attack production files or services.
"""

from __future__ import annotations

import os
import stat
import sys

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import RootsSettings
from binnacle.features.files import fd_write
from binnacle.features.files.tools import edit_file, write_file

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux FD walk")


@pytest.fixture
def allowed(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    return root, RootsSettings(default_root=root, extra_roots=())


def write(path, text, roots):
    return write_file.write_file_impl(str(path), text, roots=roots).structured_content


def edit(path, old, new, roots):
    return edit_file.edit_file_impl(
        str(path), old, new, False, roots=roots
    ).structured_content


def test_nested_create_empty_unicode_and_overwrite_preserve_permissions(allowed):
    root, roots = allowed
    path = root / "a" / "b" / "text"
    assert write(path, "héllo\n", roots)["action"] == "created"
    path.chmod(0o640)
    result = write(path, "", roots)
    assert result["action"] == "overwritten"
    assert result["previous_bytes"] == len("héllo\n".encode())
    assert path.read_bytes() == b""
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert not list(root.rglob(".binnacle-write-*"))


def test_in_root_symlink_to_file_and_nested_dir_preserve_semantics(allowed):
    root, roots = allowed
    actual = root / "actual"
    actual.mkdir()
    (actual / "target").write_text("old", encoding="utf8")
    (root / "alias").symlink_to(actual, target_is_directory=True)
    assert write(root / "alias" / "target", "new", roots)["previous_bytes"] == 3
    assert edit(root / "alias" / "target", "new", "edited", roots)["replacements"] == 1
    assert (actual / "target").read_text() == "edited"
    assert (root / "alias").is_symlink()


def test_out_of_root_symlink_rejected_with_no_mutation(allowed, tmp_path):
    root, roots = allowed
    outside = tmp_path / "not-allowed"
    outside.mkdir()
    (outside / "target").write_bytes(b"private")
    (root / "alias").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ToolError, match="outside allowed roots"):
        write(root / "alias" / "target", "bad", roots)
    with pytest.raises(ToolError, match="outside allowed roots"):
        edit(root / "alias" / "target", "private", "bad", roots)
    assert (outside / "target").read_bytes() == b"private"


def test_final_component_symlink_swap_is_refused_before_mutating_target(
    allowed, tmp_path, monkeypatch
):
    root, roots = allowed
    target = root / "victim"
    target.write_bytes(b"allowed")
    outside = tmp_path / "outside"
    outside.write_bytes(b"never overwrite")
    destination = fd_write._destination
    raced = False

    def swap(parent, name, path, tool, *, digest):
        nonlocal raced
        if not raced:
            raced = True
            target.unlink()
            target.symlink_to(outside)
        return destination(parent, name, path, tool, digest=digest)

    monkeypatch.setattr(fd_write, "_destination", swap)
    with pytest.raises(ToolError, match="changed"):
        write(target, "attack", roots)
    assert outside.read_bytes() == b"never overwrite"
    assert target.is_symlink()
    assert not list(root.glob(".binnacle-write-*"))


def test_parent_rename_and_symlink_retarget_refuses_and_cleans_temp(
    allowed, tmp_path, monkeypatch
):
    root, roots = allowed
    parent = root / "parent"
    parent.mkdir()
    target = parent / "victim"
    target.write_bytes(b"original")
    outside = tmp_path / "moved"
    alternate = tmp_path / "alternate"
    alternate.mkdir()
    (alternate / "victim").write_bytes(b"outside")
    destination = fd_write._destination
    called = 0

    def swap(parent_fd, name, path, tool, *, digest):
        nonlocal called
        info = destination(parent_fd, name, path, tool, digest=digest)
        called += 1
        if called == 2:
            parent.rename(outside)
            parent.symlink_to(alternate, target_is_directory=True)
        return info

    monkeypatch.setattr(fd_write, "_destination", swap)
    with pytest.raises(ToolError, match="changed"):
        write(target, "attack", roots)
    assert (outside / "victim").read_bytes() == b"original"
    assert (alternate / "victim").read_bytes() == b"outside"
    assert not list(outside.glob(".binnacle-write-*"))


def test_edit_same_bytes_inode_change_conflicts(allowed, monkeypatch):
    root, roots = allowed
    path = root / "editable"
    path.write_text("old")
    original = fd_write.write_bytes

    def raced_write(*args, **kwargs):
        path.unlink()
        path.write_text("old")  # same bytes, different inode
        return original(*args, **kwargs)

    monkeypatch.setattr(fd_write, "write_bytes", raced_write)
    with pytest.raises(ToolError, match="changed"):
        edit(path, "old", "new", roots)
    assert path.read_text() == "old"


def test_edit_conflict_for_content_change_before_commit(allowed, monkeypatch):
    root, roots = allowed
    path = root / "editable"
    path.write_text("old")
    original = fd_write.write_bytes

    def raced_write(*args, **kwargs):
        path.write_text("changed")
        return original(*args, **kwargs)

    monkeypatch.setattr(fd_write, "write_bytes", raced_write)
    with pytest.raises(ToolError, match="changed"):
        edit(path, "old", "new", roots)
    assert path.read_text() == "changed"


def test_fifo_refused_without_opening_blocking_writer(allowed):
    root, roots = allowed
    fifo = root / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(ToolError, match="special_file_unsupported"):
        write(fifo, "bad", roots)
    with pytest.raises(ToolError, match="special_file_unsupported"):
        edit(fifo, "old", "new", roots)


def test_directory_target_and_missing_edit_retained(allowed):
    root, roots = allowed
    with pytest.raises(ToolError, match="Use list_files"):
        write(root, "x", roots)
    with pytest.raises(ToolError, match="To create a new file"):
        edit(root / "missing", "x", "y", roots)


def test_short_writes_are_completed_without_corrupt_bytes(allowed, monkeypatch):
    root, roots = allowed
    target = root / "target"
    actual = fd_write.os.write

    def short_write(fd, data):
        return actual(fd, data[: max(1, len(data) // 5)])

    monkeypatch.setattr(fd_write.os, "write", short_write)
    content = "unicode 中文 " * 300
    assert write(target, content, roots)["bytes"] == len(content.encode("utf8"))
    assert target.read_text() == content


def test_permission_denied_preserves_no_temp_artifact(allowed):
    root, roots = allowed
    locked = root / "locked"
    locked.mkdir(mode=0o500)
    try:
        with pytest.raises(ToolError, match="Permission denied|Could not write"):
            write(locked / "target", "x", roots)
        assert not list(locked.iterdir())
    finally:
        locked.chmod(0o700)
