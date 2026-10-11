"""Real descriptor/race probes, portable to POSIX; no pathname fallback fakes."""

from __future__ import annotations

import hashlib
import os
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from tempfile import TemporaryDirectory
from threading import Event

import pytest

from binnacle.platform.contracts.capability_contracts import BudgetExceeded, UnsafePath
from binnacle.platform.contracts.file_access_contracts import FileAccess, ListRequest
from binnacle.platform.darwin import file_access, file_traversal, search_access
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
    assert [
        (e.relative_path, e.kind) for e in files.list_entries(grant, listing()).entries
    ] == [("fifo", "other")]
    with pytest.raises(UnsafePath, match="special_file"):
        files.write_bytes(grant, "fifo", b"no")
    (root / "directory").mkdir()
    with pytest.raises(UnsafePath, match="path_is_directory"):
        files.write_bytes(grant, "directory", b"no")


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


@pytest.mark.parametrize("mode", [0o4755, 0o2755, 0o1755])
@pytest.mark.parametrize("edit", [False, True])
def test_replacement_clears_special_permission_bits(tree, mode, edit):
    root, files, grant = tree
    target = root / "file"
    target.write_bytes(b"old")
    target.chmod(mode)
    files.write_bytes(
        grant,
        "file",
        b"new",
        expected_sha256=hashlib.sha256(b"old").hexdigest() if edit else None,
    )
    assert target.stat().st_mode & 0o7777 == 0o755


def test_listing_never_opens_symlinks_fifos_or_sockets(tree, monkeypatch):
    root, files, grant = tree
    (root / "link").symlink_to(root.parent)
    os.mkfifo(root / "fifo")
    with TemporaryDirectory(dir="/tmp") as short, socket.socket(socket.AF_UNIX) as sock:
        sock.bind(short + "/socket")
        os.rename(short + "/socket", root / "socket")
        real_open = os.open

        def guarded(path, flags, *args, **kwargs):
            assert path not in {"link", "fifo", "socket"}
            assert flags & os.O_NOCTTY
            return real_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", guarded)
        for glob in (None, "**/*"):
            entries = files.list_entries(grant, listing(glob=glob)).entries
            assert {(e.relative_path, e.kind) for e in entries} == (
                {(n, "other") for n in ("link", "fifo", "socket")}
                if glob is None
                else set()
            )
        monkeypatch.setattr(os, "open", real_open)
        monkeypatch.setattr(os, "open", real_open)


@pytest.mark.parametrize("directory", [False, True])
def test_listing_skips_entry_replaced_between_stat_and_open(
    tree, monkeypatch, directory
):
    root, files, grant = tree
    target = root / "race"
    if directory:
        target.mkdir()
        (target / "secret").write_text("old")
    else:
        target.write_text("old")
    (root / "good").write_text("good")
    real_open = os.open

    def swap(path, flags, *args, **kwargs):
        if path == "race":
            target.rename(root / "retained")
            if directory:
                target.mkdir()
                (target / "secret").write_text("NEW")
            else:
                target.write_text("NEW")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap)
    result = files.list_entries(grant, listing(glob="**/*"))
    assert not any(e.relative_path.startswith("race") for e in result.entries)
    assert "good" in [e.relative_path for e in result.entries]


def test_walk_does_not_serialize_read_or_close_grant(tree, monkeypatch):
    root, files, grant = tree
    (root / "file").write_text("owned")
    entered, release = Event(), Event()
    real_walk = file_traversal.Listing.walk

    def blocked_walk(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return real_walk(*args, **kwargs)

    monkeypatch.setattr(file_traversal.Listing, "walk", blocked_walk)
    with ThreadPoolExecutor(max_workers=2) as pool:
        walk = pool.submit(files.list_entries, grant, listing())
        try:
            assert entered.wait(5)
            assert pool.submit(read, files, grant, "file").result(timeout=2) == b"owned"
            pool.submit(grant.close).result(timeout=2)
        finally:
            release.set()
        assert walk.result(timeout=2).entries[0].relative_path == "file"


def test_recursive_depth_has_descriptor_budget(tree):
    root, files, grant = tree
    current = root
    for _ in range(file_traversal.MAX_WALK_DEPTH + 1):
        current /= "d"
        current.mkdir()
    with pytest.raises(BudgetExceeded, match="traversal_depth"):
        files.list_entries(grant, listing(glob="**/*"))


def test_surrogate_filename_remapping_without_filesystem_support():
    raw = b'{"type":"begin","data":{"path":{"text":"<stdin>"}}}\n'
    events = search_access._events(raw, os.fsdecode(b"bad-\xff"), False)
    assert events[0]["data"]["path"] == {"bytes": "YmFkLf8="}


def test_search_root_swap_at_native_launch_preserves_opened_bytes(tree, monkeypatch):
    from binnacle.platform.contracts.file_access_contracts import SearchRequest
    from binnacle.platform.darwin.search_access import DarwinSearchAccess

    root, files, grant = tree
    search = DarwinSearchAccess(files, rg_bin="rg")
    (root / "file").write_text("needle owned\n")
    original_popen = subprocess.Popen
    seen = []

    def swap(argv, **kwargs):
        root.rename(root.with_name("moved"))
        root.mkdir()
        (root / "file").write_text("needle SECRET\n")
        seen.append(argv)
        return original_popen(argv, **kwargs)

    monkeypatch.setattr(search_access.subprocess, "Popen", swap)
    result = search.search(
        grant, SearchRequest(".", "needle", False, 0, None, 5, 1000000, 100)
    )
    assert "SECRET" not in repr(result.events)
    assert "owned" in repr(result.events)
    assert seen[0][-1] == "-"
    assert not any(str(root) in arg for arg in seen[0])
