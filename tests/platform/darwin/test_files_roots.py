"""Real descriptor/race probes, portable to POSIX; no pathname fallback fakes."""

from __future__ import annotations

import hashlib
import os
from contextlib import closing
from dataclasses import replace

import pytest

from binnacle.platform.contracts.capability_contracts import BudgetExceeded, UnsafePath
from binnacle.platform.contracts.file_access_contracts import FileAccess, ListRequest
from binnacle.platform.darwin import file_access, file_traversal
from binnacle.platform.darwin.file_access import DarwinFileAccess
from binnacle.platform.darwin.file_traversal import validate_relative_path


@pytest.fixture
def tree(tmp_path):
    root = tmp_path.resolve() / "root"
    root.mkdir()
    with closing(DarwinFileAccess()) as files:
        grant = files.grant(root, generation="test-generation")
        yield root, files, grant


def listing(path=".", **kwargs):
    return replace(ListRequest(path, None, False, 100, 1000, 5), **kwargs)


def read(files, grant, path):
    with closing(files.open_read(grant, path)) as opened:
        return opened.read(1000)


@pytest.mark.parametrize(
    "path", ["/etc/passwd", "../x", "a/../x", "a//x", "a/./x", "x\0"]
)
def test_escaping_paths_rejected(tree, path):
    _, files, grant = tree
    for operation in (
        lambda: files.open_read(grant, path),
        lambda: files.write_bytes(grant, path, b"no"),
        lambda: files.list_entries(grant, listing(path)),
        lambda: files.nearby_hint(grant, path, max_entries=10),
    ):
        with pytest.raises(UnsafePath):
            operation()
    assert validate_relative_path(".") == ()


def test_read_metadata_and_lifetime(tree):
    root, files, grant = tree
    (root / "hello").write_bytes(b"abcdef")
    opened = files.open_read(grant, "hello")
    metadata = opened.metadata()
    assert metadata.inode == (root / "hello").stat().st_ino
    assert metadata.size_bytes == 6
    assert opened.display_path == "hello"
    assert opened.read(2) == b"ab"
    assert opened.read(10) == b"cdef"
    with pytest.raises(BudgetExceeded):
        opened.read(0)
    opened.close()
    opened.close()
    with pytest.raises(UnsafePath, match="opened_file_closed"):
        opened.metadata()
    other = files.open_read(grant, "hello")
    files.close()
    with pytest.raises(UnsafePath):
        other.read(1)
    with pytest.raises(UnsafePath):
        files.open_read(grant, "hello")


def test_moved_root_keeps_original_object_for_all_file_entrypoints(tree):
    root, files, grant = tree
    (root / "original").write_bytes(b"owned")
    moved = root.with_name("moved")
    root.rename(moved)
    root.mkdir()
    (root / "outside-secret").write_bytes(b"outside")
    (root / "original").write_bytes(b"replacement")
    assert read(files, grant, "original") == b"owned"
    result = files.list_entries(grant, listing())
    assert [e.relative_path for e in result.entries] == ["original"]
    assert files.nearby_hint(grant, "missing", max_entries=10) == ["original"]
    digest = hashlib.sha256(b"owned").hexdigest()
    files.write_bytes(grant, "original", b"edited", expected_sha256=digest)
    files.write_bytes(grant, "new", b"created")
    assert (moved / "original").read_bytes() == b"edited"
    assert (moved / "new").read_bytes() == b"created"
    assert (root / "original").read_bytes() == b"replacement"
    assert not (root / "new").exists()


@pytest.mark.parametrize("operation", ["read", "write", "edit", "list", "hint"])
def test_ancestor_symlink_swap_after_grant(tree, operation):
    root, files, grant = tree
    sub = root / "sub"
    sub.mkdir()
    (sub / "file").write_bytes(b"owned")
    outside = root.with_name("outside")
    outside.mkdir()
    (outside / "file").write_bytes(b"secret")
    sub.rename(root / "retained")
    sub.symlink_to(outside, target_is_directory=True)
    calls = {
        "read": lambda: read(files, grant, "sub/file"),
        "write": lambda: files.write_bytes(grant, "sub/file", b"bad"),
        "edit": lambda: files.write_bytes(
            grant,
            "sub/file",
            b"bad",
            expected_sha256=hashlib.sha256(b"owned").hexdigest(),
        ),
        "list": lambda: files.list_entries(grant, listing("sub")),
        "hint": lambda: files.nearby_hint(grant, "sub/missing", max_entries=10),
    }
    with pytest.raises(UnsafePath):
        calls[operation]()
    assert (outside / "file").read_bytes() == b"secret"


@pytest.mark.parametrize("operation", ["read", "write", "edit", "list", "hint"])
def test_rename_after_parent_open_does_not_reopen_path(tree, monkeypatch, operation):
    root, files, grant = tree
    sub = root / "sub"
    sub.mkdir()
    (sub / "file").write_bytes(b"owned")
    outside = root.with_name("outside")
    outside.mkdir()
    (outside / "file").write_bytes(b"secret")
    real_open = os.open
    swapped = False

    def racing_open(path, flags, *args, **kwargs):
        nonlocal swapped
        fd = real_open(path, flags, *args, **kwargs)
        if path == "sub" and not swapped:
            swapped = True
            sub.rename(root / "moved")
            sub.symlink_to(outside, target_is_directory=True)
        return fd

    monkeypatch.setattr(os, "open", racing_open)
    if operation == "read":
        assert read(files, grant, "sub/file") == b"owned"
    elif operation in ("write", "edit"):
        digest = hashlib.sha256(b"owned").hexdigest() if operation == "edit" else None
        files.write_bytes(grant, "sub/file", b"edited", expected_sha256=digest)
        assert (root / "moved/file").read_bytes() == b"edited"
    elif operation == "list":
        assert [
            e.relative_path for e in files.list_entries(grant, listing("sub")).entries
        ] == ["sub/file"]
    else:
        assert files.nearby_hint(grant, "sub/missing", max_entries=10) == ["sub/file"]
    assert (outside / "file").read_bytes() == b"secret"
    assert swapped


def test_open_file_survives_leaf_symlink_swap(tree):
    root, files, grant = tree
    target = root / "file"
    target.write_bytes(b"owned")
    outside = root.with_name("secret")
    outside.write_bytes(b"secret")
    with closing(files.open_read(grant, "file")) as opened:
        target.rename(root / "moved")
        target.symlink_to(outside)
        assert opened.read(100) == b"owned"
    with pytest.raises(UnsafePath):
        read(files, grant, "file")
    with pytest.raises(UnsafePath):
        files.write_bytes(grant, "file", b"bad")
    assert outside.read_bytes() == b"secret"


def test_write_symlink_swap_before_replace_is_denied_and_temp_removed(
    tree, monkeypatch
):
    root, files, grant = tree
    target = root / "file"
    target.write_bytes(b"owned")
    outside = root.with_name("secret")
    outside.write_bytes(b"secret")
    real_write = os.write

    def swap(fd, data):
        target.unlink()
        target.symlink_to(outside)
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", swap)
    with pytest.raises(UnsafePath):
        files.write_bytes(grant, "file", b"bad")
    assert outside.read_bytes() == b"secret"
    assert not list(root.glob(".binnacle-write-*"))


def test_modes_new_files_parents_and_hardlinks(tree):
    root, files, grant = tree
    executable = root / "run"
    executable.write_bytes(b"old")
    executable.chmod(0o755)
    os.link(executable, root / "hardlink")
    before = executable.stat().st_ino
    receipt = files.write_bytes(grant, "run", b"edited")
    assert receipt.action == "overwritten" and receipt.previous_bytes == 3
    assert executable.stat().st_mode & 0o7777 == 0o755
    assert executable.stat().st_ino != before
    assert (root / "hardlink").read_bytes() == b"old"
    # A control file observes the current umask without mutating process state.
    control = root / "control"
    control.write_bytes(b"")
    receipt = files.write_bytes(grant, "nested/new", b"new", create_parents=True)
    assert receipt.action == "created" and receipt.previous_bytes is None
    assert (root / "nested/new").stat().st_mode == control.stat().st_mode
    with pytest.raises(BudgetExceeded, match="parent_budget"):
        files.write_bytes(grant, "a/b/c", b"x", create_parents=True, max_new_parents=1)
    assert not (root / "a/b").exists()


def test_digest_conflict_and_short_write_cleanup(tree, monkeypatch):
    root, files, grant = tree
    (root / "file").write_bytes(b"newer")
    with pytest.raises(UnsafePath, match="edit_conflict"):
        files.write_bytes(
            grant, "file", b"bad", expected_sha256=hashlib.sha256(b"old").hexdigest()
        )
    with pytest.raises(UnsafePath, match="edit_conflict"):
        files.write_bytes(grant, "missing", b"bad", expected_sha256="missing")
    monkeypatch.setattr(os, "write", lambda *a: 0)
    with pytest.raises(UnsafePath, match="short_write"):
        files.write_bytes(grant, "new", b"x")
    assert not list(root.glob(".binnacle-write-*"))
    assert (root / "file").read_bytes() == b"newer"


def test_foreign_and_closed_grants(tree):
    root, files, grant = tree
    with closing(DarwinFileAccess()) as other:
        foreign = other.grant(root, generation="foreign")
        with pytest.raises(UnsafePath, match="foreign_root_grant"):
            files.list_entries(foreign, listing())
    grant.close()
    grant.close()
    with pytest.raises(UnsafePath, match="root_grant_closed"):
        files.list_entries(grant, listing())


def test_special_files_refused_without_blocking(tree):
    root, files, grant = tree
    os.mkfifo(root / "fifo")
    with pytest.raises(UnsafePath, match="special_file"):
        read(files, grant, "fifo")
    with pytest.raises(UnsafePath, match="special_file"):
        files.list_entries(grant, listing())


def test_listing_bounds_sorting_and_hidden_policy(tree, monkeypatch):
    root, files, grant = tree
    (root / "directory").mkdir()
    for name in ("a", "B", ".hidden"):
        (root / name).write_bytes(b"x")
    assert [e.relative_path for e in files.list_entries(grant, listing()).entries] == [
        "directory",
        "a",
        "B",
    ]
    assert len(files.list_entries(grant, listing(include_hidden=True)).entries) == 4
    assert files.list_entries(grant, listing(max_entries=1)).truncated
    assert files.list_entries(grant, listing(max_visited=1)).truncated
    ticks = iter([0, 100])
    monkeypatch.setattr(file_traversal.time, "monotonic", lambda: next(ticks, 100))
    assert files.list_entries(grant, listing()).truncated


def test_root_capture_refuses_symlink_ancestors(tmp_path):
    root = tmp_path.resolve()
    (root / "actual").mkdir()
    (root / "alias").symlink_to(root / "actual", target_is_directory=True)
    with closing(DarwinFileAccess()) as files, pytest.raises(UnsafePath):
        files.grant(root / "alias", generation="g")


def test_protocol_shape():
    files: FileAccess = DarwinFileAccess()
    assert isinstance(files, file_access.DarwinFileAccess)
    files.close()


@pytest.mark.parametrize(
    "pattern",
    ["*.py", "**/*.py", "sub/*.py", "sub/**", "**", "a?", "[!a]*", "sub/[ab].txt"],
)
@pytest.mark.parametrize(
    "path",
    ["a.py", "sub/a.py", "sub/deep/b.py", "sub/a.txt", "file\nname.py", "ax", "sub"],
)
def test_glob_subset_matches_existing_linux_policy(path, pattern):
    from binnacle.features.files.paths import full_match

    assert file_traversal.glob_matches(path, pattern) == full_match(
        path, pattern if "/" in pattern else f"**/{pattern}"
    )


def test_private_destination_never_uses_world_readable_temporary(tree, monkeypatch):
    root, files, grant = tree
    target = root / "private"
    target.write_bytes(b"old")
    target.chmod(0o600)
    real_write = os.write
    observed = []

    def inspect_mode(fd, data):
        observed.append(os.fstat(fd).st_mode & 0o7777)
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", inspect_mode)
    files.write_bytes(grant, "private", b"private bytes")
    assert observed == [0o600]
    assert target.stat().st_mode & 0o7777 == 0o600
