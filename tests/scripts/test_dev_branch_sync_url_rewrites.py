"""URL rewrite publication refusals against disposable Git repositories."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts import dev_branch_sync as sync
from tests import dev_branch_sync_support as support
from tests.dev_branch_sync_support import Fixture, git

pytestmark = pytest.mark.no_xdist

case = support.case
isolated_git = support.isolated_git


@pytest.mark.parametrize("rule", ["pushInsteadOf", "insteadOf"])
@pytest.mark.parametrize("scope", ["repository", "worktree"])
@pytest.mark.parametrize("field", ["url", "pushurl"])
@pytest.mark.parametrize("prefix_kind", ["exact", "partial", "empty"])
def test_matching_url_rewrite_refuses_before_mutation(
    case: Fixture,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    rule: str,
    scope: str,
    field: str,
    prefix_kind: str,
) -> None:
    git(case.wt, "push", "origin", "feature/topic")
    case.advance()
    owner = case.repo.parent / "other-owner"
    git(case.repo, "worktree", "add", "-b", "other-owner", str(owner))
    exclude = Path(git(case.wt, "rev-parse", "--git-path", "info/exclude"))
    exclude.write_text("private\n")
    private = case.wt / "private"
    private.write_bytes(b"irreplaceable\x00ignored bytes")
    checkout = case.wt if scope == "worktree" else case.repo
    options = ["--worktree"] if scope == "worktree" else ["--local"]
    if scope == "worktree":
        git(case.repo, "config", "extensions.worktreeConfig", "true")
    url = str(case.remote)
    if field == "pushurl":
        url = str(case.remote.with_name("publish.git"))
        git(checkout, "config", *options, "remote.origin.pushurl", url)
    prefix = {"exact": url, "partial": url[:-4], "empty": ""}[prefix_kind]
    key = f"url.{case.repo.parent / 'rewritten.git'}.{rule}"
    for value in ("unrelated-before:", prefix, "unrelated-after:"):
        git(checkout, "config", *options, "--add", key, value)

    def preserved() -> tuple[object, ...]:
        return (
            git(case.repo, "for-each-ref"),
            git(case.remote, "for-each-ref"),
            git(case.repo, "worktree", "list", "--porcelain"),
            private.read_bytes(),
            *((path / "shared").read_bytes() for path in (case.repo, case.wt, owner)),
            *(
                Path(
                    git(path, "rev-parse", "--path-format=absolute", "--git-path", name)
                ).read_bytes()
                for path in (case.repo, case.wt, owner)
                for name in ("HEAD", "index")
            ),
        )

    calls: list[str] = []
    original = sync.Sync.git

    def record(self: sync.Sync, path: Path, *args: str, **kwargs: Any) -> str:
        calls.append(args[0])
        return original(self, path, *args, **kwargs)

    monkeypatch.setattr(sync.Sync, "git", record)
    before = preserved()
    for mode in ("--check", "--apply"):
        code, report = case.run(capsys, mode)
        assert code == 2 and report["result"] == "refused"
        assert "Ambiguous publication" in str(report["refusals"])
        assert key.lower().rsplit(".", 1)[-1] in str(report["refusals"])
        assert preserved() == before
        case.unchanged()
    assert not {"ls-remote", "fetch", "update-ref", "merge", "rebase"}.intersection(
        calls
    )
    # Later snapshots must also refuse a rewrite introduced after initial inspection.
    instance = sync.Sync(case.repo, case.wt, "feature/topic", "origin", "master")
    assert any(rule.lower() in error for error in instance.publication_errors())


@pytest.mark.parametrize("rule", ["pushInsteadOf", "insteadOf"])
@pytest.mark.parametrize("scope", ["repository", "worktree"])
def test_unrelated_url_rewrite_allows_fast_forward(
    case: Fixture, capsys: pytest.CaptureFixture[str], rule: str, scope: str
) -> None:
    target = case.advance()
    checkout = case.wt if scope == "worktree" else case.repo
    options = ["--worktree"] if scope == "worktree" else ["--local"]
    if scope == "worktree":
        git(case.repo, "config", "extensions.worktreeConfig", "true")
    key = f"url.{case.repo.parent / 'unrelated.git'}.{rule}"
    git(checkout, "config", *options, key, "unrelated:")
    code, report = case.run(capsys, "--apply")
    assert code == 0 and report["result"] == "synced"
    assert git(case.wt, "rev-parse", "HEAD") == target
