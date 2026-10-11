"""Linux-path and Darwin adapter agree on ignore files in non-git and git roots."""

from __future__ import annotations

import os
import shutil
import subprocess
from contextlib import closing

import pytest

from binnacle.features.files.tools.list_files import _glob_mode
from binnacle.features.search.search_text_rg import run_rg
from binnacle.platform.contracts.file_access_contracts import (
    ListRequest,
    SearchRequest,
)
from binnacle.platform.darwin.file_access import DarwinFileAccess
from binnacle.platform.darwin.search_access import DarwinSearchAccess

RG = shutil.which("rg")
needs_rg = pytest.mark.skipif(RG is None, reason="ripgrep is required")

POLICIES = {
    "gitignore": (".gitignore", "*.log\n/skip/\n"),
    "ignore": (".ignore", "*.log\n/skip/\n"),
    "rgignore": (".rgignore", "*.log\n/skip/\n"),
}


ALL = {"keep.txt", "noise.log", "skip/inner.txt", "sub/deep.txt"}
HONORED = {"keep.txt", "sub/deep.txt"}


def assert_no_git_above(root):
    for parent in root.parents:
        assert not (parent / ".git").exists(), f"stray .git above test root: {parent}"


def git_init(root):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(
        ["git", "init", "-q", str(root)], check=True, env=env, capture_output=True
    )


def populate(root, policy, git):
    if git:
        git_init(root)
    name, body = POLICIES[policy]
    (root / name).write_text(body)
    (root / "skip").mkdir()
    for rel in ("keep.txt", "noise.log", "skip/inner.txt", "sub/deep.txt"):
        (root / rel).parent.mkdir(exist_ok=True)
        (root / rel).write_text("needle\n")


def linux_listing(root):
    result = _glob_mode(root, "**/*", 100, False, rg_bin=RG, timeout_s=30)
    return {
        e["path"].removeprefix(f"{root}/") for e in result.structured_content["entries"]
    }


def linux_search(root):
    events, _ = run_rg(root, "needle", False, 0, rg_bin=RG, timeout_s=30)
    return {
        e["data"]["path"]["text"].removeprefix(f"{root}/")
        for e in events
        if e["type"] == "match"
    }


@needs_rg
@pytest.mark.parametrize("git", [False, True], ids=["nongit", "git"])
@pytest.mark.parametrize("policy", sorted(POLICIES))
def test_ignore_files_listing_and_search_equal_on_both_paths(tmp_path, policy, git):
    root = tmp_path.resolve() / "root"
    root.mkdir()
    assert_no_git_above(root)
    populate(root, policy, git)
    # rg defaults: .ignore/.rgignore always apply; .gitignore only inside a git repo.
    expected = ALL if (policy == "gitignore" and not git) else HONORED
    with closing(DarwinFileAccess()) as files:
        grant = files.grant(root, generation="g")
        search = DarwinSearchAccess(files, rg_bin=RG)
        listing = files.list_entries(
            grant, ListRequest(".", "**/*", False, 100, 1000, 5)
        )
        darwin_list = {e.relative_path for e in listing.entries}
        batch = search.search(
            grant, SearchRequest(".", "needle", False, 0, None, 5, 1000000, 100)
        )
        darwin_search = {
            e["data"]["path"]["text"] for e in batch.events if e["type"] == "match"
        }
    assert linux_listing(root) == darwin_list == expected
    assert linux_search(root) == darwin_search == expected


@needs_rg
def test_ignore_file_above_grant_stays_out(tmp_path):
    outer = tmp_path.resolve() / "outer"
    root = outer / "grant"
    root.mkdir(parents=True)
    assert_no_git_above(root)
    (outer / ".gitignore").write_text("*.txt\n")
    (root / "keep.txt").write_text("needle\n")
    with closing(DarwinFileAccess()) as files:
        grant = files.grant(root, generation="g")
        listing = files.list_entries(
            grant, ListRequest(".", "**/*", False, 100, 1000, 5)
        )
    assert {e.relative_path for e in listing.entries} == {"keep.txt"}
