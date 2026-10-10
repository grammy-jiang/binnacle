"""Ownership, state, environment and race safety regressions for branch sync."""

from __future__ import annotations

import fcntl
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts import dev_branch_sync as sync
from tests import dev_branch_sync_support as support
from tests.dev_branch_sync_support import Fixture, commit, git

pytestmark = pytest.mark.no_xdist

case = support.case
isolated_git = support.isolated_git


@pytest.mark.parametrize(
    "key,value",
    [
        ("branch.feature/topic.remote", "fork"),
        ("branch.feature/topic.merge", "refs/heads/alternate"),
        ("branch.feature/topic.pushRemote", "fork"),
        ("remote.pushDefault", "fork"),
        ("remote.origin.push", "HEAD:alternate"),
        ("remote.origin.pushurl", "fork"),
        ("push.default", "matching"),
    ],
)
def test_ambiguous_publication_blocks_ff(
    case: Fixture, capsys: pytest.CaptureFixture[str], key: str, value: str
) -> None:
    git(case.repo, "remote", "add", "fork", str(case.remote))
    git(case.wt, "push", "fork", "HEAD:alternate")
    git(case.repo, "config", key, value)
    case.advance()
    code, report = case.run(capsys, "--apply")
    assert code == 2 and "Ambiguous publication" in str(report["refusals"])
    case.unchanged()


@pytest.mark.parametrize("kind", ["protected", "ref", "owner", "remote", "directory"])
def test_real_case_aliases(
    case: Fixture, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    args = []
    if kind == "protected":
        # On insensitive APFS this is the same ref; on sensitive disks it is distinct.
        git(case.repo, "update-ref", "refs/heads/Master", case.initial)
        args = ["--branch", "Master"]
    elif kind == "owner":
        git(case.repo, "switch", "master")
        # The case variant must have an actual OID on case-sensitive Linux.
        git(case.repo, "update-ref", "refs/heads/Master", case.initial)
        git(case.repo, "symbolic-ref", "HEAD", "refs/heads/Master")
    elif kind == "remote":
        git(case.remote, "update-ref", "-d", "refs/heads/master")
        git(case.remote, "update-ref", "refs/heads/Master", case.initial)
    else:
        git(case.wt, "branch", "-m", "temporary")
        name = "Feature/topic" if kind == "directory" else "feature/Topic"
        git(case.wt, "branch", "-m", name)
    before = git(case.repo, "for-each-ref")
    code, report = case.run(capsys, "--apply", *args)
    assert code == 2 and any(word in report["error"] for word in ("protected", "alias"))
    assert git(case.repo, "for-each-ref") == before


@pytest.mark.parametrize("shape", ["file", "directory", "case"])
def test_ignored_bytes_preserved(
    case: Fixture, capsys: pytest.CaptureFixture[str], shape: str
) -> None:
    exclude = Path(git(case.wt, "rev-parse", "--git-path", "info/exclude"))
    exclude.write_text("cache\nCACHE\n")
    name = "CACHE" if shape == "case" else "cache"
    path = case.wt / name
    if shape == "directory":
        path.mkdir()
        path /= "private"
    path.write_bytes(b"irreplaceable\x00local bytes")
    target = commit(case.seed, "cache", "tracked upstream\n")
    git(case.seed, "push", "origin", "master")
    assert not git(case.wt, "status", "--porcelain")
    code, report = case.run(capsys, "--apply")
    assert code == 2 and "Ignored paths collide" in str(report["refusals"])
    assert (
        report["target_sha"] == target
        and path.read_bytes() == b"irreplaceable\x00local bytes"
    )
    case.unchanged()


@pytest.mark.parametrize(
    "unsafe",
    [
        "dirty",
        "locked",
        "rebase",
        "master-owner",
        "unknown",
        "base-diverged",
        "symbolic",
        "other-owner",
    ],
)
def test_ownership_and_state_refusals(
    case: Fixture, capsys: pytest.CaptureFixture[str], unsafe: str
) -> None:
    if unsafe == "dirty":
        (case.wt / "untracked").write_text("keep")
    elif unsafe == "locked":
        git(case.repo, "worktree", "lock", str(case.wt))
    elif unsafe == "rebase":
        Path(git(case.wt, "rev-parse", "--git-path", "rebase-merge")).mkdir()
    elif unsafe == "master-owner":
        # A detached rebase retains ownership of master.
        metadata = case.repo / git(case.repo, "rev-parse", "--git-path", "rebase-merge")
        metadata.mkdir()
        (metadata / "head-name").write_text("refs/heads/master\n")
    elif unsafe == "base-diverged":
        local = commit(case.repo, "local")
        git(case.repo, "update-ref", "refs/heads/master", local)
    elif unsafe == "symbolic":
        git(
            case.repo,
            "symbolic-ref",
            "refs/heads/master",
            "refs/heads/feature/topic",
        )
    else:
        other = case.repo.parent / "other"
        git(case.repo, "worktree", "add", "--detach", str(other))
        if unsafe == "unknown":
            other.rename(case.repo.parent / "moved-owner")
        else:
            git(other, "symbolic-ref", "HEAD", "refs/heads/feature/topic")
    if unsafe == "unknown":
        # Base already current: ownership must still block a feature-only FF.
        git(case.seed, "switch", "-c", "feature/topic")
        commit(case.seed, "public")
        git(case.seed, "push", "origin", "feature/topic")
    else:
        case.advance()
    base = git(case.repo, "rev-parse", "master")
    code, report = case.run(capsys, "--apply")
    assert code == 2 and report["result"] in {"refused", "error"}
    assert git(case.repo, "rev-parse", "master") == base
    assert git(case.wt, "rev-parse", "HEAD") == case.initial


@pytest.mark.parametrize("change", ["rewrite", "delete"])
def test_tracking_history_preserved(
    case: Fixture, capsys: pytest.CaptureFixture[str], change: str
) -> None:
    public = commit(case.wt, "public")
    git(case.wt, "push", "origin", "feature/topic")
    assert case.run(capsys)[0] == 0
    case.advance()
    git(case.remote, "update-ref", "-d", "refs/heads/feature/topic")
    if change == "rewrite":
        git(case.remote, "update-ref", "refs/heads/feature/topic", case.initial)
    for _ in range(2):
        code, report = case.run(capsys, "--apply")
        assert code == 2 and "owner-reviewed" in report["error"]
        assert git(case.repo, "rev-parse", "origin/feature/topic") == public
        assert git(case.repo, "rev-parse", "origin/master") == case.initial
        case.unchanged(public)
        assert not git(case.repo, "for-each-ref", "refs/binnacle-sync/")


@pytest.mark.parametrize(
    "change", ["publish", "delete", "advance", "tracking", "local"]
)
def test_races_refuse(
    case: Fixture,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    if change != "publish":
        git(case.wt, "push", "origin", "feature/topic")
    target = case.advance()
    original, calls = sync.Sync.remote_heads, 0

    def racing_heads(self: sync.Sync) -> dict[str, str]:
        nonlocal calls
        calls += 1
        if calls == (4 if change == "local" else 2):
            if change == "tracking":
                git(case.repo, "update-ref", self.feature_tracking, target)
            elif change == "local":
                (case.wt / "concurrent").write_text("writer")
            else:
                ref = "refs/heads/feature/topic"
                git(
                    case.remote,
                    "update-ref",
                    *(("-d", ref) if change == "delete" else (ref, target)),
                )
        return original(self)

    monkeypatch.setattr(sync.Sync, "remote_heads", racing_heads)
    assert case.run(capsys, "--apply")[0] == 2
    case.unchanged()
    if change != "local":
        assert git(case.repo, "rev-parse", "origin/master") == case.initial
    assert not git(case.repo, "for-each-ref", "refs/binnacle-sync/")


@pytest.mark.parametrize("failure", ["cleanup", "snapshot", "stdout"])
def test_primary_diagnostics_survive(
    case: Fixture,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    case.advance()
    original = sync.Sync.git

    def failing_git(self: sync.Sync, path: Path, *args: str, **kwargs: Any) -> str:
        if failure == "cleanup":
            if args[0] == "fetch":
                raise sync.SyncError("primary fetch failure")
            if args[:3] == ("update-ref", "--no-deref", "-d"):
                raise OSError("secondary cleanup failure")
        if failure == "snapshot" and args[0] == "merge":
            monkeypatch.setattr(
                sync.Sync,
                "snapshot",
                lambda *a: (_ for _ in ()).throw(OSError("secondary snapshot failure")),
            )
            raise sync.SyncError("primary merge failure")
        return original(self, path, *args, **kwargs)

    if failure == "stdout":
        original_run = subprocess.run

        def stdout_failure(
            args: list[str], **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            if "fetch" in args:
                return subprocess.CompletedProcess(
                    args, 1, "stdout-only diagnostic", ""
                )
            return original_run(args, **kwargs)

        monkeypatch.setattr(subprocess, "run", stdout_failure)
    else:
        monkeypatch.setattr(sync.Sync, "git", failing_git)
    code, report = case.run(capsys, "--apply")
    assert code == 2
    assert ("stdout-only diagnostic" if failure == "stdout" else "primary") in report[
        "error"
    ]
    if failure == "cleanup":
        assert "secondary cleanup" in str(report["diagnostics"])
    if failure == "snapshot":
        assert "secondary snapshot" in report["after_error"]


@pytest.mark.parametrize(
    "override",
    [
        "GIT_NAMESPACE",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_GLOBAL",
        "hook",
    ],
)
def test_inherited_environment(
    case: Fixture,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    override: str,
) -> None:
    if override == "hook":
        for key, value in {
            "GIT_DIR": str(case.seed / ".git"),
            "GIT_WORK_TREE": str(case.seed),
            "GIT_INDEX_FILE": str(case.seed / ".git/index"),
        }.items():
            monkeypatch.setenv(key, value)
    else:
        monkeypatch.setenv(override, "unexpected")
    code, report = case.run(capsys)
    assert code == (0 if override == "hook" else 2)
    if override != "hook":
        assert "override refused" in report["error"]


def test_lock_and_standalone_cli(
    case: Fixture, capsys: pytest.CaptureFixture[str]
) -> None:
    common = Path(git(case.repo, "rev-parse", "--git-common-dir"))
    lockpath = case.repo / common / "binnacle-dev-sync.lock"
    command = [
        sys.executable,
        "-I",
        str(Path(sync.__file__).resolve()),
        "--repo",
        str(case.repo),
        "--worktree",
        str(case.wt),
        "--branch",
        "feature/topic",
        "--lock-timeout",
        "0",
    ]
    with lockpath.open("a") as lock:
        inode = lockpath.stat().st_ino
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = subprocess.run(
            [*command, "--session-lock-held"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 2 and "Timed out" in result.stdout
    assert lockpath.stat().st_ino == inode
    assert case.run(capsys)[0] == 0
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 2 and "external Pi" in result.stdout
    result = subprocess.run(
        [*command, "--session-lock-held"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0


@pytest.mark.parametrize("tracking", ["master", "feature/topic"])
@pytest.mark.parametrize("alias", [False, True])
def test_symbolic_tracking_owner_refuses_before_fetch(
    case: Fixture, capsys: pytest.CaptureFixture[str], tracking: str, alias: bool
) -> None:
    git(case.wt, "push", "origin", "feature/topic")
    git(case.repo, "update-ref", "refs/remotes/origin/feature/topic", case.initial)
    other = case.repo.parent / "tracking-owner"
    git(case.repo, "worktree", "add", "--detach", str(other))
    target = f"refs/remotes/origin/{tracking}"
    if alias:
        git(case.repo, "symbolic-ref", "refs/aliases/second", target)
        git(case.repo, "symbolic-ref", "refs/aliases/first", "refs/aliases/second")
        target = "refs/aliases/first"
    git(other, "symbolic-ref", "HEAD", target)
    case.advance()
    git(case.seed, "push", "origin", "HEAD:feature/topic")

    def preserved() -> tuple[object, ...]:
        return (
            git(case.repo, "for-each-ref"),
            git(other, "rev-parse", "HEAD"),
            git(other, "symbolic-ref", "--no-recurse", "HEAD"),
            *(
                Path(
                    git(path, "rev-parse", "--path-format=absolute", "--git-path", name)
                ).read_bytes()
                for path in (case.repo, case.wt, other)
                for name in ("HEAD", "index")
            ),
            *((path / "shared").read_bytes() for path in (case.repo, case.wt, other)),
        )

    before = preserved()
    for mode in ("--check", "--apply"):
        code, report = case.run(capsys, mode)
        assert code == 2 and "HEAD owns a ref" in report["error"]
        assert preserved() == before
        assert not (other / "upstream").exists()
        case.unchanged()


def test_merge_options_refuse_before_local_mutations(
    case: Fixture, capsys: pytest.CaptureFixture[str]
) -> None:
    target = case.advance()
    key = "branch.feature/topic.mergeOptions"
    git(case.repo, "config", key, "--squash")
    index = Path(git(case.wt, "rev-parse", "--git-path", "index"))
    before = index.read_bytes(), (case.wt / "shared").read_bytes()
    tracking_before = git(
        case.repo,
        "for-each-ref",
        "--format=%(refname):%(objectname)",
        "refs/remotes/origin",
    )
    for mode in ("--check", "--apply"):
        code, report = case.run(capsys, mode)
        assert code == 2 and "mergeOptions refused" in str(report["refusals"])
        case.unchanged()
        assert (
            git(
                case.repo,
                "for-each-ref",
                "--format=%(refname):%(objectname)",
                "refs/remotes/origin",
            )
            == tracking_before
        )
        assert (index.read_bytes(), (case.wt / "shared").read_bytes()) == before
        assert not (case.wt / "upstream").exists()
    git(case.repo, "config", "--unset-all", key)
    code, report = case.run(capsys, "--apply")
    assert code == 0 and report["result"] == "synced"
    assert git(case.repo, "rev-parse", "master") == target
    assert git(case.wt, "rev-parse", "HEAD") == target
    assert not git(case.wt, "status", "--porcelain")
