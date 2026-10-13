"""list_files LIST mode refuses every walk failure with a code (r6 W3 SP1).

SRC-W2-06: _opened mapped only ENOENT, ENOTDIR and EACCES; ELOOP, EMFILE
and ENAMETOOLONG escaped as raw OSError, and the race directory_not_found
had no nearby hint. Each failure is injected after the path check, at the
descriptor walk, so resolve_path still accepts the listed directory.
"""

import errno
import os
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import RootsSettings
from binnacle.errors import CodedToolError
from binnacle.features.files import fd_walk
from binnacle.features.files.tools import list_files as lf

# The process descriptor table: /proc/self/fd on Linux, /dev/fd on Darwin.
FD_DIR = "/proc/self/fd" if os.path.isdir("/proc/self/fd") else "/dev/fd"


@pytest.fixture
def tree(tmp_path: Path) -> dict:
    root = tmp_path.resolve() / "root"
    (root / "d").mkdir(parents=True)
    (root / "d" / "f.txt").write_text("f")
    (root / "a.txt").write_text("a")
    roots = RootsSettings(default_root=root, extra_roots=())
    return {"root": root, "listed": root / "d", "roots": roots}


def refusal(tree: dict) -> CodedToolError:
    with pytest.raises(ToolError) as exc:
        lf.list_files_impl(str(tree["listed"]), None, 200, False, roots=tree["roots"])
    assert isinstance(exc.value, CodedToolError)
    return exc.value


def fail_open_of(monkeypatch, name: str, code: int) -> None:
    """os.open of the listed directory's name fails with code; others pass."""
    real_open = os.open

    def failing(path, flags, *args, **kwargs):
        if path == name and kwargs.get("dir_fd") is not None:
            raise OSError(code, os.strerror(code))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(fd_walk.os, "open", failing)


def test_a_listed_directory_swapped_for_a_symlink_is_path_changed(tree, monkeypatch):
    # The no-follow open refuses the symlink: ENOTDIR on Linux (O_DIRECTORY
    # is checked first), ELOOP where O_NOFOLLOW is; both are path_changed.
    listed, real_open_root = tree["listed"], fd_walk.open_root

    def swap_then_open(root, *args):
        listed.rename(listed.with_name("d.keep"))
        listed.symlink_to(listed.with_name("d.keep"))
        return real_open_root(root, *args)

    monkeypatch.setattr(fd_walk, "open_root", swap_then_open)
    err = refusal(tree)
    assert err.telemetry_code == "path_changed"
    assert str(err).startswith(f"Directory changed during the listing: {listed}.")


def test_eloop_from_the_walk_is_path_changed(tree, monkeypatch):
    fail_open_of(monkeypatch, "d", errno.ELOOP)
    assert refusal(tree).telemetry_code == "path_changed"


def test_a_descriptor_shortage_is_too_many_open_files(tree, monkeypatch):
    fail_open_of(monkeypatch, "d", errno.EMFILE)
    err = refusal(tree)
    assert err.telemetry_code == "too_many_open_files"
    assert str(err) == (
        f"list_files could not open {tree['listed']}: the server has too many "
        f"open files. Retry."
    )


def test_enfile_is_too_many_open_files(tree, monkeypatch):
    fail_open_of(monkeypatch, "d", errno.ENFILE)
    assert refusal(tree).telemetry_code == "too_many_open_files"


def test_a_name_too_long_is_file_io_failed(tree, monkeypatch):
    fail_open_of(monkeypatch, "d", errno.ENAMETOOLONG)
    err = refusal(tree)
    assert err.telemetry_code == "file_io_failed"
    reason = os.strerror(errno.ENAMETOOLONG)
    assert str(err) == f"Cannot list {tree['listed']}: {reason}."


def test_a_shortage_reading_the_listed_directory_is_coded(tree, monkeypatch):
    # os.listdir(fd) dups the descriptor, so EMFILE can come from the read.
    real_listdir = os.listdir

    def failing(path=None):
        if isinstance(path, int):
            raise OSError(errno.EMFILE, os.strerror(errno.EMFILE))
        return real_listdir(path)

    monkeypatch.setattr(os, "listdir", failing)
    assert refusal(tree).telemetry_code == "too_many_open_files"


def test_a_directory_removed_in_the_race_gets_the_nearby_hint(tree, monkeypatch):
    listed, real_open_root = tree["listed"], fd_walk.open_root

    def remove_then_open(root, *args):
        (listed / "f.txt").unlink()
        listed.rmdir()
        return real_open_root(root, *args)

    monkeypatch.setattr(fd_walk, "open_root", remove_then_open)
    err = refusal(tree)
    assert err.telemetry_code == "directory_not_found"
    assert str(err) == (
        f"Directory not found: {listed}. Files in {tree['root']}: a.txt. "
        f"Use list_files for more."
    )


@pytest.mark.parametrize("code", [errno.ELOOP, errno.EMFILE, errno.ENAMETOOLONG])
def test_no_descriptor_leaks_across_coded_refusals(tree, monkeypatch, code):
    fail_open_of(monkeypatch, "d", code)
    before = len(os.listdir(FD_DIR))
    for _ in range(5):
        refusal(tree)
    assert len(os.listdir(FD_DIR)) <= before
