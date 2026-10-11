"""Darwin glob listings are ordered by the Linux rule (r5 L3b, SD-60 item 2).

Linux lists a glob with ``rg --files --sortr modified``: newest modification
time first, entries with an equal time left in the walk order. The Darwin
traversal must not impose its own tie-break (it used to add the relative path),
or an ``lf.glob``-style listing differs from Linux whenever mtimes tie.
Display order only: the set of entries is covered by the neighbouring suites.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from contextlib import closing

import pytest

from binnacle.features.files.tools.list_files import _glob_mode
from binnacle.platform.contracts.file_access_contracts import ListRequest
from binnacle.platform.darwin.file_access import DarwinFileAccess

RG = shutil.which("rg")
needs_rg = pytest.mark.skipif(RG is None, reason="ripgrep is required")

BASE_NS = 1_700_000_000 * 10**9
SECOND = 10**9


def stamp(root, relative, step, text="x"):
    """Give a file a modification time `step` seconds after a fixed base."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    when = BASE_NS + step * SECOND
    os.utime(path, ns=(when, when))


def git_init(root):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(
        ["git", "init", "-q", str(root)], check=True, env=env, capture_output=True
    )


def darwin_order(root, glob, include_hidden=False, max_entries=100):
    with closing(DarwinFileAccess()) as files:
        grant = files.grant(root, generation="g")
        listing = files.list_entries(
            grant, ListRequest(".", glob, include_hidden, max_entries, 1000, 5)
        )
    return [e.relative_path for e in listing.entries]


def linux_order(root, glob, include_hidden=False, max_results=100):
    result = _glob_mode(
        root, glob, max_results, include_hidden, rg_bin=RG, timeout_s=30
    )
    return [
        e["path"].removeprefix(f"{root}/") for e in result.structured_content["entries"]
    ]


@pytest.fixture
def root(tmp_path):
    resolved = tmp_path.resolve() / "root"
    resolved.mkdir()
    for parent in resolved.parents:
        assert not (parent / ".git").exists(), f"stray .git above test root: {parent}"
    return resolved


def test_distinct_mtimes_are_newest_first_regardless_of_name(root):
    # Mirrors the shape of the Linux lf.glob row: nested, mixed case, newest first.
    for step, name in enumerate(
        ["lossy.txt", "sub/n.txt", "empty.txt", "five.txt", "Big.txt", "huge.txt"]
    ):
        stamp(root, name, step)
    assert darwin_order(root, "**/*.txt") == [
        "huge.txt",
        "Big.txt",
        "five.txt",
        "empty.txt",
        "sub/n.txt",
        "lossy.txt",
    ]


def test_mixed_case_and_nesting_do_not_reorder_by_name(root):
    names = ["B.txt", "a.txt", "c/Z.txt", "c/a.txt", "c/d/e.txt", "_u.txt"]
    for step, name in enumerate(names):
        stamp(root, name, step)
    assert darwin_order(root, "**/*.txt") == list(reversed(names))


def test_equal_mtimes_are_not_sorted_by_path(root):
    # A path tie-break would always list these alphabetically, which is not
    # what rg does; the stable sort leaves the walk order untouched.
    names = ["b.txt", "C.txt", "a.txt", "sub/Z.txt", "sub/a.txt", "_u.txt"]
    for name in names:
        stamp(root, name, 0)
    walked = darwin_order(root, "**/*.txt")
    assert sorted(walked) == sorted(names)
    unsorted_walk = []

    def collect(directory, prefix=""):
        with os.scandir(directory) as it:
            for child in it:
                if child.is_dir(follow_symlinks=False):
                    collect(child.path, prefix + child.name + "/")
                else:
                    unsorted_walk.append(prefix + child.name)

    collect(root)
    assert walked == unsorted_walk


@needs_rg
@pytest.mark.parametrize("ties", [False, True], ids=["distinct", "tied"])
@pytest.mark.parametrize("glob", ["**/*", "*.txt", "**/*.md", "sub/**"])
def test_nested_mixed_case_order_equals_linux_rule(root, glob, ties):
    names = [
        "B.txt",
        "a.txt",
        "z.md",
        "sub/Z.txt",
        "sub/a.txt",
        "sub/deep/e.md",
        "sub/deep/E.txt",
        "_u.txt",
        "Sub2/x.txt",
        "dir with space/f.txt",
    ]
    for step, name in enumerate(names):
        stamp(root, name, 0 if ties else step % 7)
    assert darwin_order(root, glob) == linux_order(root, glob)


@needs_rg
@pytest.mark.parametrize("ties", [False, True], ids=["distinct", "tied"])
def test_hidden_files_with_include_hidden_equal_linux_rule(root, ties):
    # Mirrors lf.gitignore_hidden: a hidden file listed among visible ones.
    git_init(root)
    stamp(root, ".gitignore", 0 if ties else 1, "ignored.txt\n")
    stamp(root, "ignored.txt", 0 if ties else 2)
    stamp(root, "kept.txt", 0 if ties else 3)
    stamp(root, ".hid", 0 if ties else 4)
    stamp(root, ".cfg/inner.txt", 0 if ties else 5)
    on = darwin_order(root, "**/*", include_hidden=True)
    assert on == linux_order(root, "**/*", include_hidden=True)
    assert ".git" not in {part for path in on for part in path.split("/")}
    assert "ignored.txt" not in on
    if not ties:
        assert on == [".cfg/inner.txt", ".hid", "kept.txt", ".gitignore"]
    off = darwin_order(root, "**/*", include_hidden=False)
    assert off == linux_order(root, "**/*", include_hidden=False)
    assert off == [name for name in on if not name.startswith(".") and "/." not in name]


@needs_rg
@pytest.mark.parametrize("policy", [".gitignore", ".ignore", ".rgignore"])
@pytest.mark.parametrize("git", [False, True], ids=["nongit", "git"])
def test_ignore_policy_listing_order_equals_linux_rule(root, policy, git):
    if git:
        git_init(root)
    stamp(root, policy, 9, "*.log\n/skip/\n")
    for step, name in enumerate(
        ["keep.txt", "noise.log", "skip/inner.txt", "sub/deep.txt", "sub/Ab.txt"]
    ):
        stamp(root, name, step)
    assert darwin_order(root, "**/*", include_hidden=True) == linux_order(
        root, "**/*", include_hidden=True
    )


@needs_rg
def test_truncation_keeps_the_same_newest_entries_as_linux(root):
    for step, name in enumerate(["a.txt", "b/c.txt", "D.txt", "b/e.txt", "f.txt"]):
        stamp(root, name, step)
    assert (
        darwin_order(root, "**/*.txt", max_entries=3)
        == linux_order(root, "**/*.txt", max_results=3)
        == ["f.txt", "b/e.txt", "D.txt"]
    )
