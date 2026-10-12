"""list_files GLOB mode sizes no outside object (r6 W2 X3c, SD-76).

rg --files lists by path string and never lists a symlink. A race wrapper
runs the real rg, then swaps a listed file (or its directory) for a symlink
to an outside object before the tool sizes it. r6 sized the outside object
through p.stat(); the head lstat-s each listed name relative to a directory
descriptor walked no-follow from '/', and omits a swapped entry.
"""

import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

from binnacle.config import RootsSettings
from binnacle.features.files.tools import list_files as lf

# The process descriptor table: /proc/self/fd on Linux, /dev/fd on Darwin.
FD_DIR = "/proc/self/fd" if os.path.isdir("/proc/self/fd") else "/dev/fd"
# Parity finding PF-T3-01 (R6W2-T3): Darwin keeps TRAVERSE_FLAGS = O_RDONLY
# (fd_walk.py, DARWIN-FOLLOWUP-exec-only-dirs), so an execute-only directory
# differs from Linux; reported to the Supervisor, never loosened.
PF_T3_01 = pytest.mark.xfail(
    sys.platform == "darwin",
    strict=True,
    reason="PF-T3-01: execute-only directory parity (DARWIN-FOLLOWUP-exec-only-dirs)",
)

RG = shutil.which("rg") or "rg"
OUTSIDE_SIZE = 4321


def wrapper(tmp: Path, after: str) -> str:
    """An rg stand-in: the real rg, then 'after', then rg's output."""
    script = tmp / "rg-race.sh"
    script.write_text(
        "#!/bin/sh\n"
        f'out=$("{RG}" "$@"); code=$?\n'
        f"{after}\n"
        'printf "%s\\n" "$out"\n'
        "exit $code\n"
    )
    script.chmod(0o700)
    return str(script)


@pytest.fixture
def tree(tmp_path: Path) -> dict:
    root = tmp_path / "root"
    (root / "d").mkdir(parents=True)
    (root / "a.txt").write_text("a" * 10)
    (root / "d" / "b.txt").write_text("b" * 20)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.txt").write_text("x" * OUTSIDE_SIZE)
    (outside / "b.txt").write_text("y" * OUTSIDE_SIZE)
    roots = RootsSettings(default_root=root, extra_roots=())
    return {"root": root, "outside": outside, "roots": roots, "tmp": tmp_path}


def glob(tree: dict, rg_bin: str = RG, pattern: str = "*.txt") -> dict:
    result = lf.list_files_impl(
        str(tree["root"]), pattern, 200, False, roots=tree["roots"], rg_bin=rg_bin
    )
    payload = result.structured_content
    assert payload is not None
    return payload


def sizes(payload: dict) -> dict:
    return {
        os.path.relpath(e["path"], payload["path"]): e.get("bytes")
        for e in payload["entries"]
    }


def test_benign_glob_sizes_are_unchanged(tree):
    payload = glob(tree)
    assert sizes(payload) == {"a.txt": 10, "d/b.txt": 20}
    assert payload["count"] == 2 and payload["truncated"] is False


def test_a_file_swapped_for_an_outside_symlink_is_omitted(tree):
    root, outside = tree["root"], tree["outside"]
    rg = wrapper(
        tree["tmp"], f'rm "{root}/a.txt"; ln -s "{outside}/a.txt" "{root}/a.txt"'
    )
    payload = glob(tree, rg)
    assert OUTSIDE_SIZE not in sizes(payload).values()
    assert sizes(payload) == {"d/b.txt": 20}
    assert payload["count"] == 1


def test_a_directory_swapped_for_an_outside_symlink_is_omitted(tree):
    root, outside = tree["root"], tree["outside"]
    rg = wrapper(
        tree["tmp"], f'mv "{root}/d" "{root}/d.keep"; ln -s "{outside}" "{root}/d"'
    )
    payload = glob(tree, rg)
    assert OUTSIDE_SIZE not in sizes(payload).values()
    assert sizes(payload) == {"a.txt": 10}


def test_a_directory_swapped_for_a_file_is_omitted(tree):
    root = tree["root"]
    rg = wrapper(tree["tmp"], f'mv "{root}/d" "{root}/d.keep"; echo x > "{root}/d"')
    assert sizes(glob(tree, rg)) == {"a.txt": 10}


def test_a_file_removed_after_listing_keeps_its_entry_without_bytes(tree):
    root = tree["root"]
    rg = wrapper(tree["tmp"], f'rm "{root}/a.txt"')
    assert sizes(glob(tree, rg)) == {"a.txt": None, "d/b.txt": 20}


@PF_T3_01
def test_an_execute_only_ancestor_still_sizes(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root ignores modes")
    gate = tmp_path / "gate"
    root = gate / "root"
    root.mkdir(parents=True)
    (root / "f.txt").write_text("z" * 7)
    tree = {"root": root, "roots": RootsSettings(default_root=root, extra_roots=())}
    gate.chmod(stat.S_IXUSR)
    try:
        payload = glob(tree)
    finally:
        gate.chmod(0o700)
    assert sizes(payload) == {"f.txt": 7}


def test_a_glob_through_a_cross_root_link_base_is_unchanged(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    (b / "s").mkdir(parents=True)
    (b / "s" / "f.txt").write_text("q" * 3)
    (a / "to_b").symlink_to(b / "s")
    roots = RootsSettings(default_root=a, extra_roots=(b,))
    payload = lf.list_files_impl(
        str(a / "to_b"), "*.txt", 200, False, roots=roots, rg_bin=RG
    ).structured_content
    assert payload is not None
    assert [(e["path"], e.get("bytes")) for e in payload["entries"]] == [
        (str(b / "s" / "f.txt"), 3)
    ]


def test_glob_sizing_leaks_no_descriptor(tree):
    root, outside = tree["root"], tree["outside"]
    rg = wrapper(
        tree["tmp"],
        f'[ -L "{root}/a.txt" ] || {{ rm "{root}/a.txt"; '
        f'ln -s "{outside}/a.txt" "{root}/a.txt"; }}',
    )
    before = len(os.listdir(FD_DIR))
    for _ in range(30):
        glob(tree, rg)
        glob(tree)
    assert len(os.listdir(FD_DIR)) == before
