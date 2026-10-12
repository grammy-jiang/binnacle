"""fd_walk traverse flags and open_verified's parent_fd (r6 W3 OS1).

TRAVERSE_FLAGS is O_PATH on Linux and O_SEARCH on Darwin
(DARWIN-FOLLOWUP-exec-only-dirs): search permission only, never listable,
always no-follow per component. SRC-W2-03: open_verified has no by-path
mode, so no caller can open through an intermediate symlink.
"""

from __future__ import annotations

import inspect
import os
import stat
from pathlib import Path

import pytest

from binnacle.features.files import fd_walk


def test_traverse_flags_are_no_follow_directory_flags():
    flags = fd_walk.TRAVERSE_FLAGS
    assert flags & os.O_NOFOLLOW and flags & os.O_DIRECTORY and flags & os.O_CLOEXEC
    assert flags != fd_walk.DIRECTORY_FLAGS


def test_a_traverse_descriptor_cannot_be_listed():
    fd = os.open("/", fd_walk.TRAVERSE_FLAGS)
    try:
        with pytest.raises(OSError):
            os.listdir(fd)
    finally:
        os.close(fd)


def test_the_walk_passes_through_an_execute_only_directory(tmp_path: Path):
    if os.geteuid() == 0:
        pytest.skip("root ignores modes")
    base = tmp_path.resolve()
    (base / "x" / "y").mkdir(parents=True)
    (base / "x" / "y" / "f.txt").write_text("hi")
    (base / "x" / "link").symlink_to("y", target_is_directory=True)
    mode = stat.S_IMODE((base / "x").stat().st_mode)
    (base / "x").chmod(0o100)
    try:
        with fd_walk.open_root(base / "x" / "y", fd_walk.DIRECTORY_FLAGS) as fd:
            assert os.listdir(fd) == ["f.txt"]
        with fd_walk.open_root(base) as root_fd:
            with fd_walk.directory_at(root_fd, ("x", "y")) as fd:
                assert os.stat("f.txt", dir_fd=fd).st_size == 2
            link = fd_walk.directory_at(root_fd, ("x", "link"))
            with pytest.raises(OSError), link:  # No-follow per component.
                pass
            listed = fd_walk.directory_at(root_fd, ("x",), fd_walk.DIRECTORY_FLAGS)
            with pytest.raises(PermissionError), listed:  # Listing still needs read.
                pass
    finally:
        (base / "x").chmod(mode)


def test_open_verified_requires_parent_fd():
    parameter = inspect.signature(fd_walk.open_verified).parameters["parent_fd"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty
    assert parameter.annotation in (int, "int")
    with pytest.raises(TypeError):
        fd_walk.open_verified("/etc/hosts", [Path("/etc")], (0, 0))
