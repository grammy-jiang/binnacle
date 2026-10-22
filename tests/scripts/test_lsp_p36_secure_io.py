"""Descriptor-based path policy: symlink, hardlink, owner, mode and root checks."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.lsp_p36_secure_io import PathPolicy, PathRefused, read_file
from tests.fixtures.lsp.trust_chain import process_owner_policy, write_private

POLICY = process_owner_policy()


def _file(tmp_path: Path) -> Path:
    return write_private(tmp_path / "dir" / "file.json", b"{}")


def test_regular_private_file_is_read(tmp_path):
    found = read_file(_file(tmp_path), POLICY, 1024)
    assert found.data == b"{}" and found.uid == os.geteuid()


@pytest.mark.parametrize(
    "text", ["relative/file", "/a//b", "/a/./b", "/a/../b", "/a/b/", "/", "/a\x00b"]
)
def test_non_canonical_paths_refused(text):
    with pytest.raises(PathRefused):
        read_file(text, POLICY, 1024)


def test_leaf_symlink_refused(tmp_path):
    target = _file(tmp_path)
    link = tmp_path / "dir" / "link.json"
    link.symlink_to(target)
    with pytest.raises(PathRefused, match="path_symlink_or_unreadable"):
        read_file(link, POLICY, 1024)


def test_ancestor_symlink_refused(tmp_path):
    _file(tmp_path)
    (tmp_path / "alias").symlink_to(tmp_path / "dir")
    with pytest.raises(PathRefused, match="path_symlink_refused"):
        read_file(tmp_path / "alias" / "file.json", POLICY, 1024)


def test_hardlink_refused(tmp_path):
    target = _file(tmp_path)
    os.link(target, tmp_path / "dir" / "second.json")
    with pytest.raises(PathRefused, match="file_hardlink_refused"):
        read_file(target, POLICY, 1024)


@pytest.mark.parametrize("mode", [0o620, 0o602, 0o4600, 0o2600, 0o1600])
def test_unsafe_file_mode_refused(tmp_path, mode):
    path = _file(tmp_path)
    path.chmod(mode)
    with pytest.raises(PathRefused, match="file_mode_unsafe"):
        read_file(path, POLICY, 1024)


def test_foreign_owner_refused(tmp_path):
    other = PathPolicy(owner_uids=frozenset({os.geteuid() + 1}), check_ancestors=False)
    with pytest.raises(PathRefused, match="file_owner_untrusted"):
        read_file(_file(tmp_path), other, 1024)


def test_writable_ancestor_and_foreign_ancestor_refused(tmp_path):
    path = _file(tmp_path)
    (tmp_path / "dir").chmod(0o770)
    try:
        with pytest.raises(PathRefused, match="path_ancestor_writable"):
            read_file(path, POLICY, 1024)
    finally:
        (tmp_path / "dir").chmod(0o700)
    other = PathPolicy(
        owner_uids=frozenset({os.geteuid() + 1}), allow_sticky_ancestors=True
    )
    if os.geteuid() != 0:
        with pytest.raises(PathRefused, match="path_ancestor_owner_untrusted"):
            read_file(path, other, 1024)


def test_world_writable_sticky_ancestor_needs_explicit_allowance(tmp_path):
    path = _file(tmp_path)
    strict = PathPolicy(owner_uids=frozenset({os.geteuid()}))
    # /tmp is root-owned, sticky and world-writable on this host.
    if Path("/tmp").stat().st_mode & 0o002 and str(path).startswith("/tmp/"):
        with pytest.raises(PathRefused, match="path_ancestor_writable"):
            read_file(path, strict, 1024)


def test_fifo_and_oversize_and_empty_refused(tmp_path):
    (tmp_path / "dir").mkdir(mode=0o700)
    fifo = tmp_path / "dir" / "pipe"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(PathRefused, match="file_not_regular"):
        read_file(fifo, POLICY, 1024)
    big = write_private(tmp_path / "big" / "f", b"x" * 2048)
    with pytest.raises(PathRefused, match="file_size_invalid"):
        read_file(big, POLICY, 1024)
    empty = write_private(tmp_path / "empty" / "f", b"")
    with pytest.raises(PathRefused, match="file_size_invalid"):
        read_file(empty, POLICY, 1024)


def test_forbidden_root_refused_by_identity_not_name(tmp_path):
    path = _file(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path / "dir")  # Forbidden roots are resolved by inode.
    policy = PathPolicy(
        owner_uids=POLICY.owner_uids,
        allow_sticky_ancestors=True,
        forbidden_roots=(str(alias),),
    )
    with pytest.raises(PathRefused, match="path_inside_untrusted_root"):
        read_file(path, policy, 1024)


def test_errors_never_contain_the_path(tmp_path):
    secret = tmp_path / "secret-name-marker" / "f"
    with pytest.raises(PathRefused) as exc:
        read_file(secret, POLICY, 1024)
    assert "secret-name-marker" not in str(exc.value)
