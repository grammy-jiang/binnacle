"""Darwin returns the Linux sentence for the same condition (R4 lane J8).

Differential: every case runs the shared tool implementation twice over one
temporary tree, once through the legacy pathname path (what Linux executes)
and once through opened-root ``FileToolAccess`` on Darwin adapters, and
requires byte-identical text. Structured notes are compared where Linux sets
one.
"""

import os
import subprocess
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import ListFilesSettings, ReadFileSettings, RootsSettings
from binnacle.errors import CodedToolError
from binnacle.features.files import paths
from binnacle.features.files.tools.edit_file import edit_file_impl
from binnacle.features.files.tools.list_files import list_files_impl
from binnacle.features.files.tools.read_file import read_file_impl
from binnacle.features.files.tools.write_file import write_file_impl
from binnacle.features.search.tools.search_text import search_text_impl
from binnacle.platform.contracts.capability_contracts import Capability, CapabilityState
from binnacle.platform.darwin.file_access import DarwinFileAccess
from binnacle.platform.darwin.search_access import DarwinSearchAccess


@pytest.fixture
def tree(tmp_path: Path):
    root = (tmp_path / "root").resolve()
    outside = (tmp_path / "outside").resolve()
    (root / "d" / "sub").mkdir(parents=True)
    outside.mkdir()
    (outside / "secret.txt").write_text("hello secret\n")
    (root / "d" / "five.txt").write_text("a\nb\nc\nd\ne\n")
    (root / "d" / "sub" / "n.txt").write_text("alpha\nbeta needle\ngamma\n")
    (root / "d" / "big.txt").write_bytes(b"x" * 3000)
    (root / "d" / "escape").symlink_to(outside, target_is_directory=True)
    (root / "g").mkdir()
    (root / "g" / ".gitignore").write_text("ign.txt\n")
    (root / "g" / "kept.txt").write_text("k\n")
    for i in range(5):
        (root / "d" / f"m{i}.log").write_text("log\n")
        os.utime(root / "d" / f"m{i}.log", (1_000_000 + i, 1_000_000 + i))
    roots = RootsSettings(default_root=root, extra_roots=())
    files = DarwinFileAccess()
    access = paths.FileToolAccess(
        roots=roots,
        files=files,
        search=DarwinSearchAccess(files, rg_bin="rg"),
        generation="error-text-parity",
        capability=Capability(CapabilityState.LIMITED, "test", "opened-object"),
    )
    try:
        yield root, outside, roots, access
    finally:
        access.close()


def _run(fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs)
    except (CodedToolError, ToolError) as exc:
        return "error", str(exc), None
    return "ok", result.content[0].text, result.structured_content


def _both(fn, tree, *args, **kwargs):
    _, _, roots, access = tree
    linux = _run(fn, *args, roots=roots, **kwargs)
    darwin = _run(fn, *args, roots=roots, file_access=access, **kwargs)
    return linux, darwin


def _same_text(fn, tree, *args, **kwargs):
    linux, darwin = _both(fn, tree, *args, **kwargs)
    assert darwin[:2] == linux[:2]
    return linux, darwin


@pytest.mark.parametrize(
    "rel",
    ["d/nope.txt", "d", "d/../../outside/secret.txt", "d/escape/secret.txt", "~/x"],
)
def test_read_file_errors(tree, rel, monkeypatch):
    root, outside, _, _ = tree
    monkeypatch.setenv("HOME", str(outside.parent / "home"))
    path = str(outside / "secret.txt") if rel.startswith("d/..") else str(root / rel)
    if rel == "~/x":
        path = "~/x"
    linux, _ = _same_text(read_file_impl, tree, path, 1, None)
    assert linux[0] == "error"


def test_read_file_too_large_uses_the_size_sentence(tree):
    root, _, roots, access = tree
    small = ReadFileSettings(max_file_bytes=1024 * 1024)
    (root / "d" / "huge.bin").write_bytes(b"x" * (1024 * 1024 + 1))
    path = str(root / "d" / "huge.bin")
    linux = _run(read_file_impl, path, 1, None, roots=roots, settings=small)
    darwin = _run(
        read_file_impl, path, 1, None, roots=roots, file_access=access, settings=small
    )
    assert darwin[:2] == linux[:2]
    assert "the limit is 1 MB" in darwin[1]


@pytest.mark.parametrize(
    "rel", ["nope", "d/five.txt", "d/escape/x", "../outside", "d/empty_dir_missing/z"]
)
def test_list_files_errors(tree, rel):
    root, outside, _, _ = tree
    path = str(outside) if rel == "../outside" else str(root / rel)
    linux, _ = _same_text(list_files_impl, tree, path, None, 50, False)
    assert linux[0] == "error"


def test_list_files_outside_default_path(tree):
    _same_text(list_files_impl, tree, "/usr", None, 50, False)


@pytest.mark.parametrize(
    ("glob", "limit"),
    [
        ("**/*.log", 50),
        ("**/*.log", 2),
        ("*.zzz", 50),
        ("**/*.txt", 50),
        ("**/*.log", 5),
    ],
)
def test_list_files_glob_summaries_and_notes(tree, glob, limit):
    root = tree[0]
    linux, darwin = _same_text(
        list_files_impl, tree, str(root / "d"), glob, limit, False
    )
    assert darwin[2].get("note") == linux[2].get("note")
    assert darwin[2]["truncated"] == linux[2]["truncated"]
    assert darwin[2]["count"] == linux[2]["count"]


def test_list_files_glob_respects_gitignore_with_linux_summary(tree):
    root = tree[0]
    # rg only honors .gitignore inside a git work tree; pin that so the result
    # does not depend on where the host places temporary directories.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "init", "-q", str(root / "g")], check=True, env=env)
    (root / "g" / "ign.txt").write_text("i\n")
    linux, _ = _same_text(list_files_impl, tree, str(root / "g"), "**/*", 50, False)
    assert linux[1].startswith("Found 1 files matching")


def test_list_files_plain_listing_truncation_note(tree):
    root = tree[0]
    for i in range(5):
        (root / "g" / f"f{i}.txt").write_text("x\n")
    linux, darwin = _same_text(list_files_impl, tree, str(root / "g"), None, 3, False)
    assert darwin[2].get("note") == linux[2].get("note")
    assert linux[1].startswith("Listed first 3 of ")


def test_list_files_cap_is_still_enforced(tree):
    root, _, roots, access = tree
    capped = ListFilesSettings(max_results_cap=2)
    darwin = _run(
        list_files_impl,
        str(root / "d"),
        "**/*.log",
        50,
        False,
        roots=roots,
        file_access=access,
        settings=capped,
    )
    assert darwin[2]["count"] == 2


@pytest.mark.parametrize("rel", ["nope", "../outside"])
def test_search_text_path_errors(tree, rel):
    root, outside, _, _ = tree
    path = str(outside) if rel == "../outside" else str(root / rel)
    linux, _ = _same_text(
        search_text_impl, tree, "needle", path, None, False, None, False, 50
    )
    assert linux[0] == "error"


def test_search_text_invalid_regex_carries_the_rg_diagnostic(tree):
    root = tree[0]
    linux, _ = _same_text(
        search_text_impl,
        tree,
        "(?:(unclosed)",
        str(root / "d"),
        None,
        False,
        None,
        False,
        50,
    )
    assert linux[1].startswith("ripgrep rejected the search: rg: regex parse error")


def test_search_text_no_match_note_and_summary(tree):
    root = tree[0]
    linux, darwin = _same_text(
        search_text_impl, tree, "zzzqqq", str(root / "d"), None, False, None, False, 50
    )
    assert darwin[2]["note"] == linux[2]["note"]
    assert linux[1].startswith("No matches for")


@pytest.mark.parametrize(
    ("kwargs", "names_only", "limit"),
    [({}, False, 50), ({}, False, 2), ({}, True, 50), ({"glob": "m1*"}, False, 50)],
)
def test_search_text_hit_summaries(tree, kwargs, names_only, limit):
    root = tree[0]
    pattern = "log" if limit == 2 or kwargs else "needle|log"
    linux, darwin = _same_text(
        search_text_impl,
        tree,
        pattern,
        str(root / "d"),
        kwargs.get("glob"),
        False,
        None,
        names_only,
        limit,
    )
    assert darwin[2].get("note") == linux[2].get("note")
    assert darwin[2]["count"] == linux[2]["count"]
    if limit == 2:
        assert darwin[2]["note"].startswith("Showing first 2 of 5 matches; narrow")
        assert darwin[1].endswith("; showing first 2.")


@pytest.mark.parametrize("rel", ["d", "d/escape/secret.txt", "d/five.txt/child"])
def test_write_file_errors(tree, rel):
    root = tree[0]
    linux, _ = _same_text(write_file_impl, tree, str(root / rel), "x")
    assert linux[0] == "error"


def test_write_file_outside_root(tree):
    _same_text(write_file_impl, tree, "/usr/r4-should-not-exist", "x")


@pytest.mark.parametrize("rel", ["d/nope.txt", "d", "d/escape/secret.txt"])
def test_edit_file_errors(tree, rel):
    root = tree[0]
    linux, _ = _same_text(edit_file_impl, tree, str(root / rel), "a", "b", False)
    assert linux[0] == "error"


def test_linux_branches_are_unreachable_without_file_access(tree):
    root, _, roots, _ = tree
    # Legacy path: the shared layer is not consulted for text at all.
    status, text, _ = _run(
        read_file_impl, str(root / "d/nope.txt"), 1, None, roots=roots
    )
    assert status == "error" and text.startswith("File not found: ")


def test_inside_root_dotdot_keeps_the_terse_refusal(tree):
    root, _, _, access = tree
    access.require("read_file")
    with pytest.raises(CodedToolError, match="Unsafe relative path."):
        access.read(str(root / "d" / ".." / "d" / "five.txt"), 1024)


@pytest.mark.parametrize("limit", [3, 50])
def test_search_text_auto_context_follows_the_complete_result_rule(tree, limit):
    root = tree[0]
    (root / "d" / "lines.txt").write_text("".join(f"hit {i}\n" for i in range(10)))
    linux, darwin = _same_text(
        search_text_impl,
        tree,
        "hit",
        str(root / "d" / "lines.txt"),
        None,
        False,
        None,
        False,
        limit,
    )
    assert darwin[2]["entries"] == linux[2]["entries"]
    assert darwin[2].get("note") == linux[2].get("note")
