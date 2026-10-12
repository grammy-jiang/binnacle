"""Darwin adapter traverses execute-only directories like Linux (r6 W3 OS1).

DARWIN-FOLLOWUP-exec-only-dirs / PF-T3-01: file_traversal opens a directory
it only passes through with TRAVERSE_FLAGS (O_SEARCH on Darwin, O_PATH on
Linux, where portability tests run this adapter), so an execute-only
directory in the root chain or inside a root no longer refuses the grant,
a read, a write or a listing below it. A directory that is listed is still
opened for reading, and every open stays no-follow per component.
"""

from __future__ import annotations

import os
import stat
from contextlib import closing
from pathlib import Path

import pytest

from binnacle.platform.contracts.capability_contracts import (
    PermissionDenied,
    UnsafePath,
)
from binnacle.platform.contracts.file_access_contracts import ListRequest
from binnacle.platform.darwin import file_traversal
from binnacle.platform.darwin.file_access import DarwinFileAccess

SECRET = b"s" * 4321  # A size that appears nowhere else in the fixture.


@pytest.fixture
def tree(tmp_path: Path):
    """gate (execute-only) / root / {x (execute-only) / y / g.txt, a.txt}."""
    if os.geteuid() == 0:
        pytest.skip("root ignores modes")
    base = tmp_path.resolve()
    gate = base / "gate"
    root = gate / "root"
    (root / "x" / "y").mkdir(parents=True)
    (root / "x" / "y" / "g.txt").write_text("in x")
    (root / "a.txt").write_text("hello")
    (base / "out").mkdir()
    (base / "out" / "secret.txt").write_bytes(SECRET)
    changed: list[tuple[Path, int]] = []

    def execute_only(path: Path) -> None:
        changed.append((path, stat.S_IMODE(path.stat().st_mode)))
        path.chmod(0o100)

    yield {"base": base, "gate": gate, "root": root, "execute_only": execute_only}
    for path, mode in reversed(changed):
        path.chmod(mode)


def request(path: str) -> ListRequest:
    return ListRequest(path, None, False, 100, 1000, 5)


def names(listing) -> dict[str, str]:
    return {e.relative_path: e.kind for e in listing.entries}


def test_traverse_flags_stay_no_follow_and_cannot_list():
    flags = file_traversal.TRAVERSE_FLAGS
    assert flags & os.O_NOFOLLOW and flags & os.O_DIRECTORY and flags & os.O_CLOEXEC
    assert file_traversal.DIRECTORY_FLAGS & os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        with pytest.raises(OSError):
            os.listdir(fd)  # EBADF: a traverse descriptor is never enumerated.
    finally:
        os.close(fd)


def test_an_execute_only_ancestor_grants_lists_reads_and_writes(tree):
    tree["execute_only"](tree["gate"])
    with closing(DarwinFileAccess()) as files:
        grant = files.grant(tree["root"], generation="g")
        assert names(files.list_entries(grant, request("."))) == {
            "x": "directory",
            "a.txt": "file",
        }
        opened = files.open_read(grant, "a.txt")
        try:
            assert os.read(opened.fd, 100) == b"hello"
        finally:
            opened.close()
        files.write_bytes(grant, "new/n.txt", b"new", create_parents=True)
    assert (tree["root"] / "new" / "n.txt").read_bytes() == b"new"


def test_listing_below_an_execute_only_in_root_directory(tree):
    tree["execute_only"](tree["root"] / "x")
    with closing(DarwinFileAccess()) as files:
        grant = files.grant(tree["root"], generation="g")
        listing = files.list_entries(grant, request("x/y"))
        assert names(listing) == {"x/y/g.txt": "file"}
        opened = files.open_read(grant, "x/y/g.txt")
        opened.close()


def test_the_listed_execute_only_directory_itself_is_still_refused(tree):
    tree["execute_only"](tree["root"] / "x")
    with closing(DarwinFileAccess()) as files:
        grant = files.grant(tree["root"], generation="g")
        with pytest.raises(PermissionDenied) as failure:
            files.list_entries(grant, request("x"))
    assert failure.value.code == "permission_denied_tcc_possible"


def test_an_execute_only_root_grants_but_its_listing_is_refused(tree):
    tree["execute_only"](tree["root"])
    with closing(DarwinFileAccess()) as files:
        grant = files.grant(tree["root"], generation="g")
        with pytest.raises(PermissionDenied):
            files.list_entries(grant, request("."))
        opened = files.open_read(grant, "a.txt")  # Passes through the root.
        opened.close()


def test_links_through_an_execute_only_in_root_directory(tree):
    root = tree["root"]
    (root / "via").symlink_to("x/y/g.txt")
    (root / "up").symlink_to("x/../a.txt")
    (root / "abs").symlink_to(root / "x" / "y" / "g.txt")
    (root / "esc").symlink_to(tree["base"] / "out" / "secret.txt")
    tree["execute_only"](root / "x")
    with closing(DarwinFileAccess()) as files:
        grant = files.grant(root, generation="g")
        listing = files.list_entries(grant, request("."))
    entries = {e.relative_path: e for e in listing.entries}
    resolved = {name: entries[name].target_kind for name in ("via", "up", "abs")}
    assert resolved == {"via": "file", "up": "file", "abs": "file"}
    assert entries["esc"].target_kind is None
    assert len(SECRET) not in {e.size_bytes for e in entries.values()}


def test_a_symlink_component_is_still_refused_under_an_execute_only_dir(tree):
    root = tree["root"]
    (root / "x" / "link").symlink_to(tree["base"] / "out", target_is_directory=True)
    tree["execute_only"](root / "x")
    with closing(DarwinFileAccess()) as files:
        grant = files.grant(root, generation="g")
        for operation in (
            lambda: files.open_read(grant, "x/link/secret.txt"),
            lambda: files.list_entries(grant, request("x/link")),
            lambda: files.write_bytes(grant, "x/link/w.txt", b"w"),
        ):
            with pytest.raises(UnsafePath) as failure:
                operation()
            assert failure.value.code == "symlink_or_wrong_path_type"
    assert not (tree["base"] / "out" / "w.txt").exists()


def test_a_symlink_ancestor_of_the_root_is_still_refused(tree):
    alias = tree["base"] / "alias"
    alias.symlink_to(tree["gate"], target_is_directory=True)
    tree["execute_only"](tree["gate"])
    with closing(DarwinFileAccess()) as files, pytest.raises(UnsafePath):
        files.grant(alias / "root", generation="g")
