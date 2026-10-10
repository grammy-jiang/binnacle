"""Branch synchronization regressions against disposable local remotes."""

from __future__ import annotations

import subprocess

import pytest

from tests import dev_branch_sync_support as support
from tests.dev_branch_sync_support import Fixture, commit, git

pytestmark = pytest.mark.no_xdist

case = support.case
isolated_git = support.isolated_git


@pytest.mark.parametrize("missing_base", [False, True])
def test_tracking_check_and_safe_apply(
    case: Fixture, capsys: pytest.CaptureFixture[str], missing_base: bool
) -> None:
    if missing_base:
        git(case.repo, "branch", "-d", "master")
        git(case.repo, "update-ref", "-d", "refs/remotes/origin/master")
    target = case.advance()
    code, report = case.run(capsys)
    assert code == 1 and report["result"] == "needs-sync"
    assert git(case.repo, "rev-parse", "origin/master") == target
    assert git(case.wt, "rev-parse", "HEAD") == case.initial
    code, report = case.run(capsys, "--apply")
    assert code == 0 and report["actions"] == [
        "fast-forward-local-base",
        "fast-forward-feature",
    ]
    assert git(case.repo, "rev-parse", "master") == target
    assert git(case.wt, "rev-parse", "HEAD") == target
    assert case.run(capsys, "--apply")[1]["actions"] == []


@pytest.mark.parametrize("history", ["behind", "ahead", "diverged", "both", "guard"])
@pytest.mark.parametrize("mode", ["--check", "--apply"])
def test_selected_remote_containment(
    case: Fixture, capsys: pytest.CaptureFixture[str], history: str, mode: str
) -> None:
    git(case.wt, "push", "origin", "feature/topic")
    git(case.seed, "switch", "-c", "feature/topic")
    public = case.initial
    if history != "ahead":
        public = commit(case.seed, "public")
        git(case.seed, "push", "origin", "feature/topic")
    local = (
        commit(case.wt, "local") if history in {"ahead", "diverged"} else case.initial
    )
    if history in {"both", "guard"}:
        git(case.seed, "switch", "master")
        case.advance()
        if history == "both":
            git(case.seed, "switch", "feature/topic")
            git(case.seed, "merge", "--no-edit", "master")
            public = git(case.seed, "rev-parse", "HEAD")
            git(case.seed, "push", "origin", "feature/topic")
    assert not git(case.repo, "for-each-ref", "refs/remotes/origin/feature/topic")
    code, report = case.run(capsys, mode)
    assert git(case.repo, "rev-parse", "origin/feature/topic") == public
    if history in {"diverged", "guard"}:
        assert code == 2 and report["result"] == "refused"
        case.unchanged(local)
    elif history == "ahead":
        assert code == (1 if mode == "--check" else 0)
        assert report["result"] == "local-ahead"
    else:
        assert code == (1 if mode == "--check" else 0)
        assert git(case.wt, "rev-parse", "HEAD") == (
            local if mode == "--check" else public
        )
    assert git(case.remote, "rev-parse", "feature/topic") == public


@pytest.mark.parametrize("kind", ["private", "fork", "alternate", "merge"])
def test_never_rewrites_feature(
    case: Fixture, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    if kind == "merge":
        git(case.wt, "switch", "-c", "side")
        commit(case.wt, "shared", "side\n")
        git(case.wt, "switch", "feature/topic")
    commit(case.wt, "shared", "feature\n")
    if kind == "merge":
        result = subprocess.run(
            ["git", "-C", str(case.wt), "merge", "side"],
            capture_output=True,
            check=False,
        )
        assert result.returncode == 1
        commit(case.wt, "shared", "merge-only resolution\n")
        assert len(git(case.wt, "rev-list", "--parents", "-1", "HEAD").split()) == 3
    feature = git(case.wt, "rev-parse", "HEAD")
    original_bytes = (case.wt / "shared").read_bytes()
    if kind == "fork":
        fork = case.remote.with_name("fork.git")
        git(case.repo, "init", "--bare", str(fork))
        git(case.repo, "remote", "add", "fork", str(fork))
        git(case.wt, "push", "-u", "fork", "HEAD:alternate")
    elif kind == "alternate":
        git(case.wt, "push", "-u", "origin", "HEAD:alternate")
    git(case.repo, "branch", "other-owner", feature)
    git(case.repo, "config", "rebase.updateRefs", "true")
    target = case.advance()
    code, report = case.run(capsys, "--apply")
    assert code == 2 and "manual-rebase-required" in str(report["refusals"])
    assert feature in str(report["refusals"]) and target in str(report["refusals"])
    assert report["before"]["publication_state"] == "not-observed-on-selected-remote"
    case.unchanged(feature)
    assert git(case.repo, "rev-parse", "other-owner") == feature
    assert (case.wt / "shared").read_bytes() == original_bytes
    assert not git(case.wt, "status", "--porcelain")
