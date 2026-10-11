"""Guards for the RX3a2 follow-ups N1 and N3 (r6 W2 X3b, SD-76).

RX3a2-N1: the link walk opens each intermediate component no-follow
(fd_walk._walk_link). A component swapped for a symlink to an outside
directory between its lstat and its open must not be followed (mutant N12).
RX3a2-N3: open_verified compares paths by component, not by string prefix
(mutant N7), and ENOTDIR is path_changed (mutant N8).
"""

import os
import sys
from pathlib import Path

import pytest

from binnacle.config import RootsSettings
from binnacle.errors import CodedToolError
from binnacle.features.files import fd_walk
from binnacle.features.files.tools import list_files as lf

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux walk")
SECRET_SIZE = 4321  # A size that appears nowhere else in the fixture.


def test_the_link_walk_never_follows_an_intermediate_swap(tmp_path, monkeypatch):
    base = tmp_path.resolve()
    root, outside = base / "root", base / "outside"
    (root / "a").mkdir(parents=True)
    outside.mkdir()
    (root / "a" / "t.txt").write_text("in")
    (outside / "t.txt").write_text("S" * SECRET_SIZE)
    (root / "l").symlink_to("a/t.txt")
    swapped: list[str] = []
    real_lstat = os.lstat

    def swap_after_lstat(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        caller = sys._getframe(1).f_code.co_name
        if path == "a" and caller == "_walk_link" and not swapped:
            swapped.append(path)
            (root / "a").rename(base / "a.old")
            (root / "a").symlink_to(outside, target_is_directory=True)
        return info

    monkeypatch.setattr(fd_walk.os, "lstat", swap_after_lstat)
    roots = RootsSettings(default_root=root, extra_roots=())
    payload = lf.list_files_impl(str(root), None, 200, False, roots=roots)
    assert payload.structured_content is not None
    entries = payload.structured_content["entries"]
    sizes = {Path(e["path"]).name: e.get("bytes") for e in entries}
    assert swapped == ["a"]  # The race fired inside the link walk.
    assert "l" not in sizes
    assert SECRET_SIZE not in sizes.values()


def ident(path: Path) -> tuple[int, int]:
    info = os.lstat(path)
    return info.st_dev, info.st_ino


def refusal(path: Path, roots, expected) -> str:
    before = len(os.listdir("/proc/self/fd"))
    with pytest.raises(CodedToolError) as exc:
        fd_walk.open_verified(path, roots, expected)
    assert len(os.listdir("/proc/self/fd")) == before
    return exc.value.telemetry_code


def test_a_sibling_prefix_root_is_outside(tmp_path):
    base = tmp_path.resolve()
    root, sibling = base / "root", base / "rootX"
    root.mkdir()
    sibling.mkdir()
    path = sibling / "p"
    path.write_text("sibling")
    assert refusal(path, (root,), ident(path)) == "path_outside_root"


def test_a_file_used_as_a_directory_is_path_changed(tmp_path):
    root = tmp_path.resolve() / "root"
    root.mkdir()
    (root / "o.txt").write_text("o")
    assert refusal(root / "o.txt" / "p", (root,), (0, 0)) == "path_changed"
