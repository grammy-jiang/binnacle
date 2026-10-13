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

# Per-test platform pin, rather than a collection-wide skip: the repository
# deliberately forbids false-green all-skipped files (macos_skip_table).
LINUX_ONLY = pytest.mark.skipif(sys.platform != "linux", reason="Linux FD walk")


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


@LINUX_ONLY
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


@LINUX_ONLY
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


@LINUX_ONLY
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


@LINUX_ONLY
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


@LINUX_ONLY
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


@LINUX_ONLY
def test_edit_same_bytes_inode_change_conflicts(allowed, monkeypatch):
    root, roots = allowed
    path = root / "editable"
    path.write_text("old")
    original = fd_write.write_bytes

    def raced_write(*args, **kwargs):
        path.rename(root / "previous-inode")  # hold the original inode allocated
        path.write_text("old")  # same bytes, provably different inode
        return original(*args, **kwargs)

    monkeypatch.setattr(fd_write, "write_bytes", raced_write)
    with pytest.raises(ToolError, match="changed"):
        edit(path, "old", "new", roots)
    assert path.read_text() == "old"


@LINUX_ONLY
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


@LINUX_ONLY
def test_fifo_refused_without_opening_blocking_writer(allowed):
    root, roots = allowed
    fifo = root / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(ToolError, match="special_file_unsupported"):
        write(fifo, "bad", roots)
    with pytest.raises(ToolError, match="special_file_unsupported"):
        edit(fifo, "old", "new", roots)


@LINUX_ONLY
def test_directory_target_and_missing_edit_retained(allowed):
    root, roots = allowed
    with pytest.raises(ToolError, match="Use list_files"):
        write(root, "x", roots)
    with pytest.raises(ToolError, match="To create a new file"):
        edit(root / "missing", "x", "y", roots)


@LINUX_ONLY
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


@LINUX_ONLY
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


@LINUX_ONLY
def test_direct_fd_root_scope_and_directory_target_refuse(allowed, tmp_path):
    root, _ = allowed
    with pytest.raises(ToolError, match="outside allowed roots"):
        fd_write.write_bytes(
            tmp_path / "not-allowed", (root,), b"x", create_parents=True
        )
    with pytest.raises(ToolError, match="directory"):
        fd_write.write_bytes(root, (root,), b"x", create_parents=True)


@LINUX_ONLY
def test_linux_only_backend_refuses_other_platform_before_mutations(
    allowed, monkeypatch
):
    root, _ = allowed
    monkeypatch.setattr(fd_write.sys, "platform", "darwin")
    with pytest.raises(RuntimeError, match="Linux-only"):
        fd_write.write_bytes(root / "f", (root,), b"x", create_parents=True)
    assert not (root / "f").exists()


@LINUX_ONLY
def test_missing_parent_on_edit_refuses_without_creation(allowed):
    root, _ = allowed
    with pytest.raises(ToolError, match="changed"):
        fd_write.read_for_edit(root / "missing" / "file", (root,))
    assert not (root / "missing").exists()


@LINUX_ONLY
def test_concurrent_parent_creation_reopened_nofollow(allowed, monkeypatch):
    root, roots = allowed
    real_mkdir = os.mkdir
    calls = []

    def other_writer_created(name, *args, **kwargs):
        if name == "race" and kwargs.get("dir_fd") is not None:
            calls.append(name)
            real_mkdir(name, *args, **kwargs)
            raise FileExistsError("concurrent creator")
        return real_mkdir(name, *args, **kwargs)

    monkeypatch.setattr(fd_write.os, "mkdir", other_writer_created)
    assert write(root / "race" / "child.txt", "ok", roots)["action"] == "created"
    assert calls == ["race"]


@LINUX_ONLY
def test_regular_ancestor_write_existing_error_and_edit_refusal(allowed):
    root, roots = allowed
    parent = root / "parent-is-file"
    parent.write_bytes(b"hello")
    with pytest.raises(ToolError, match="File exists"):
        write(parent / "child", "bad", roots)
    with pytest.raises(ToolError, match="changed"):
        fd_write.read_for_edit(parent / "child", (root,))
    assert parent.read_bytes() == b"hello"


@LINUX_ONLY
def test_direct_edit_target_missing_after_resolution_refuses(allowed):
    root, _ = allowed
    with pytest.raises(ToolError, match="changed"):
        fd_write.write_bytes(
            root / "missing.txt",
            (root,),
            b"new",
            create_parents=False,
            expected_sha256="bad",
            expected_identity=(1, 2),
        )


@LINUX_ONLY
def test_open_target_denial_rechecks_regular_and_rejects_unknown(allowed, monkeypatch):
    root, _ = allowed
    file = root / "f"
    file.write_bytes(b"old")
    original_open = fd_write.os.open
    original_stat = fd_write.os.stat

    def deny(path, *args, **kwargs):
        if path == "f" and kwargs.get("dir_fd") is not None:
            raise PermissionError("test-only injected EACCES")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(fd_write.os, "open", deny)
    with pytest.raises(PermissionError):
        fd_write.write_bytes(file, (root,), b"x", create_parents=True)

    def gone(path, *args, **kwargs):
        if path == "f" and kwargs.get("dir_fd") is not None:
            raise FileNotFoundError("test-only disappeared after denial")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(fd_write.os, "stat", gone)
    with pytest.raises(PermissionError):
        fd_write.write_bytes(file, (root,), b"x", create_parents=True)
    assert file.read_bytes() == b"old"


@LINUX_ONLY
def test_read_for_edit_nofollow_final_swap_and_denied_open(allowed, monkeypatch):
    root, _ = allowed
    file = root / "target.txt"
    file.write_bytes(b"old")
    original_open = fd_write.os.open
    error = [OSError(os.ELOOP if hasattr(os, "ELOOP") else 40, "link swapped")]

    def inject(path, *args, **kwargs):
        if path == "target.txt" and kwargs.get("dir_fd") is not None:
            raise error[0]
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(fd_write.os, "open", inject)
    with pytest.raises(ToolError, match="changed"):
        fd_write.read_for_edit(file, (root,))
    error[0] = PermissionError("injected read refusal")
    with pytest.raises(PermissionError):
        fd_write.read_for_edit(file, (root,))
    assert file.read_bytes() == b"old"


@LINUX_ONLY
def test_read_for_edit_failed_special_fd_is_never_read(allowed, monkeypatch):
    root, _ = allowed
    file = root / "device-shaped"
    file.write_bytes(b"old")
    original_open = fd_write.os.open

    def deny(path, *args, **kwargs):
        if path == "device-shaped" and kwargs.get("dir_fd") is not None:
            raise PermissionError("simulated special device open refusal")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(fd_write.os, "open", deny)
    monkeypatch.setattr(fd_write.fd_walk, "_failed_open_special", lambda *_: True)
    with pytest.raises(ToolError, match="special_file_unsupported"):
        fd_write.read_for_edit(file, (root,))
    assert file.read_bytes() == b"old"


@LINUX_ONLY
def test_read_for_edit_final_inode_changed_before_stat(allowed, monkeypatch):
    root, _ = allowed
    file = root / "f"
    file.write_bytes(b"old")
    old_stat = fd_write.os.stat
    moved = [False]

    def change_at_stat(path, *args, **kwargs):
        if path == "f" and kwargs.get("dir_fd") is not None and not moved[0]:
            moved[0] = True
            file.rename(root / "original")
            file.write_bytes(b"old")
        return old_stat(path, *args, **kwargs)

    monkeypatch.setattr(fd_write.os, "stat", change_at_stat)
    with pytest.raises(ToolError, match="changed"):
        fd_write.read_for_edit(file, (root,))
    assert moved[0]
    assert (root / "original").read_bytes() == b"old"


@LINUX_ONLY
def test_read_for_edit_modified_while_reading_refuses(allowed, monkeypatch):
    root, _ = allowed
    file = root / "f"
    file.write_bytes(b"old")
    original_read = fd_write.os.read
    once = [False]

    def race(fd, size):
        chunk = original_read(fd, size)
        if chunk and not once[0]:
            once[0] = True
            with file.open("ab") as stream:
                stream.write(b"late")
        return chunk

    monkeypatch.setattr(fd_write.os, "read", race)
    with pytest.raises(ToolError, match="changed"):
        fd_write.read_for_edit(file, (root,))
    assert file.read_bytes() == b"oldlate"


@LINUX_ONLY
def test_zero_write_is_io_failure_and_temp_removed(allowed, monkeypatch):
    root, roots = allowed
    file = root / "target"
    original = fd_write.os.write
    called = [False]

    def zero(fd, data):
        if not called[0]:
            called[0] = True
            return 0
        return original(fd, data)

    monkeypatch.setattr(fd_write.os, "write", zero)
    with pytest.raises(ToolError, match="Could not write"):
        write(file, "abc", roots)
    assert called[0]
    assert not file.exists()
    assert not list(root.glob(".binnacle-write-*"))


@LINUX_ONLY
def test_write_detects_target_changed_during_temp_write(allowed, monkeypatch):
    root, roots = allowed
    file = root / "f"
    file.write_bytes(b"old")
    real_write = fd_write.os.write
    mutated = [False]

    def writer(fd, data):
        result = real_write(fd, data)
        if not mutated[0]:
            mutated[0] = True
            file.write_bytes(b"concurrent external update")
        return result

    monkeypatch.setattr(fd_write.os, "write", writer)
    with pytest.raises(ToolError, match="changed"):
        write(file, "new", roots)
    assert file.read_bytes() == b"concurrent external update"
    assert not list(root.glob(".binnacle-write-*"))


@LINUX_ONLY
def test_expected_edit_digest_and_identity_need_agree(allowed):
    root, _ = allowed
    file = root / "f"
    file.write_bytes(b"old")
    st = file.stat()
    with pytest.raises(ToolError, match="changed"):
        fd_write.write_bytes(
            file,
            (root,),
            b"new",
            create_parents=False,
            expected_sha256="bad",
            expected_identity=(st.st_dev, st.st_ino),
        )


@LINUX_ONLY
def test_linux_write_io_error_uses_prior_surface_sentence(allowed, monkeypatch):
    root, roots = allowed

    def no_space(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(fd_write, "write_bytes", no_space)
    with pytest.raises(ToolError, match="Could not write .*No space left"):
        write(root / "f", "data", roots)


@LINUX_ONLY
def test_non_linux_file_dispatch_preserves_pathname_fallback(allowed, monkeypatch):
    """Dispatch regression: simulated non-Linux without a native provider."""
    root, roots = allowed
    monkeypatch.setattr(write_file.sys, "platform", "darwin")
    file = root / "sub" / "text"
    assert write(file, "new", roots)["action"] == "created"
    assert write(file, "later", roots)["previous_bytes"] == 3
    assert file.read_text() == "later"
    parent_file = root / "file-as-dir"
    parent_file.write_text("old")
    with pytest.raises(ToolError, match="Could not write .*File exists"):
        write(parent_file / "child", "bad", roots)
    assert parent_file.read_text() == "old"
