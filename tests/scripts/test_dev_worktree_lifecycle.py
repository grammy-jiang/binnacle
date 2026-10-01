"""Transactional creation and guarded cleanup of development worktrees."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts import dev_worktree_lifecycle as lifecycle
from scripts import dev_worktrees as wt
from scripts.dev_common import CommandResult

BASE_SHA = "a" * 40


def _which(name: str) -> str | None:
    return "/usr/bin/git" if name == "git" else None


def test_create_worktree_bootstraps_new_branch(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    target = tmp_path / "repo-feature"
    calls: list[tuple[str, ...]] = []
    bootstrapped: list[Path] = []

    def run(argv: Any, cwd: Path) -> CommandResult:
        command = tuple(argv)
        calls.append(command)
        if "check-ref-format" in command:
            return CommandResult(0, "feature/x\n")
        if "show-ref" in command:
            return CommandResult(1, "")
        if command[-3:-1] == ("--verify", "master^{commit}"):
            raise AssertionError(command)
        if command[-2:] == ("--verify", "master^{commit}"):
            return CommandResult(0, BASE_SHA + "\n")
        if command[1:4] == ("worktree", "add", "-b"):
            return CommandResult(0, "created")
        raise AssertionError(command)

    def bootstrap(path: Path) -> int:
        bootstrapped.append(path)
        return 0

    ok, detail = lifecycle.create_worktree(
        root,
        path=target,
        branch="feature/x",
        base="master",
        run=run,
        which=_which,
        bootstrap=bootstrap,
    )

    assert ok
    assert "bootstrapped" in detail
    assert bootstrapped == [target.resolve()]
    assert any(
        command[1:4] == ("worktree", "add", "-b") and command[4] == "feature/x"
        for command in calls
    )


def test_create_worktree_refuses_nested_target_and_existing_origin_branch(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    ok, detail = lifecycle.create_worktree(
        root,
        path=root / "nested",
        branch="feature/x",
        base="master",
        run=lambda argv, cwd: CommandResult(0, ""),
        which=_which,
        bootstrap=lambda path: 0,
    )
    assert not ok and "outside the current worktree" in detail

    target = tmp_path / "repo-feature"

    def run(argv: Any, cwd: Path) -> CommandResult:
        command = tuple(argv)
        if "check-ref-format" in command:
            return CommandResult(0, "")
        if command[-1] == "refs/heads/feature/x":
            return CommandResult(1, "")
        if command[-1] == "refs/remotes/origin/feature/x":
            return CommandResult(0, "")
        raise AssertionError(command)

    ok, detail = lifecycle.create_worktree(
        root,
        path=target,
        branch="feature/x",
        base="master",
        run=run,
        which=_which,
        bootstrap=lambda path: 0,
    )
    assert not ok and "origin branch already exists" in detail


def test_create_worktree_rolls_back_unchanged_bootstrap_failure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    target = tmp_path / "repo-feature"
    calls: list[tuple[str, ...]] = []

    def run(argv: Any, cwd: Path) -> CommandResult:
        command = tuple(argv)
        calls.append(command)
        if "check-ref-format" in command:
            return CommandResult(0, "")
        if "show-ref" in command:
            return CommandResult(1, "")
        if command[-2:] == ("--verify", "master^{commit}"):
            return CommandResult(0, BASE_SHA + "\n")
        if command[1:4] == ("worktree", "add", "-b"):
            return CommandResult(0, "")
        if command[-2:] == ("status", "--porcelain"):
            return CommandResult(0, "")
        if command[-2:] == ("rev-parse", "HEAD"):
            return CommandResult(0, BASE_SHA + "\n")
        if command[1:4] == ("worktree", "remove", "--force"):
            return CommandResult(0, "")
        if command[1:3] == ("branch", "-D"):
            return CommandResult(0, "")
        raise AssertionError(command)

    ok, detail = lifecycle.create_worktree(
        root,
        path=target,
        branch="feature/x",
        base="master",
        run=run,
        which=_which,
        bootstrap=lambda path: 7,
    )

    assert not ok
    assert "rolled back" in detail
    assert any(command[1:4] == ("worktree", "remove", "--force") for command in calls)
    assert any(command[1:3] == ("branch", "-D") for command in calls)


def test_create_worktree_preserves_changed_tree_after_bootstrap_failure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    target = tmp_path / "repo-feature"
    calls: list[tuple[str, ...]] = []

    def run(argv: Any, cwd: Path) -> CommandResult:
        command = tuple(argv)
        calls.append(command)
        if "check-ref-format" in command:
            return CommandResult(0, "")
        if "show-ref" in command:
            return CommandResult(1, "")
        if command[-2:] == ("--verify", "master^{commit}"):
            return CommandResult(0, BASE_SHA + "\n")
        if command[1:4] == ("worktree", "add", "-b"):
            return CommandResult(0, "")
        if command[-2:] == ("status", "--porcelain"):
            return CommandResult(0, "?? evidence.txt\n")
        if command[-2:] == ("rev-parse", "HEAD"):
            return CommandResult(0, BASE_SHA + "\n")
        raise AssertionError(command)

    ok, detail = lifecycle.create_worktree(
        root,
        path=target,
        branch="feature/x",
        base="master",
        run=run,
        which=_which,
        bootstrap=lambda path: 9,
    )

    assert not ok
    assert "preserved changed worktree" in detail
    assert not any("remove" in command for command in calls)


def _status(
    path: Path,
    *,
    branch: str = "feature/old",
    dirty: int | None = 0,
    merged: bool | None = True,
    locked: str | None = None,
    bare: bool = False,
) -> wt.WorktreeStatus:
    return wt.WorktreeStatus(
        path=str(path),
        branch=branch,
        head=BASE_SHA[:12],
        upstream="origin/feature/old",
        ahead=0,
        behind=0,
        merged_to_master=merged,
        dirty_changes=dirty,
        venv=True,
        lock="current",
        locked=locked,
        flags=("ok",),
        bare=bare,
    )


def test_cleanup_refuses_current_dirty_unmerged_and_locked(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    ok, detail = lifecycle.cleanup_worktree(
        root,
        path=root,
        delete_branch=False,
        apply=True,
        run=lambda argv, cwd: CommandResult(0, ""),
        which=_which,
    )
    assert not ok and "current worktree" in detail

    target = tmp_path / "candidate"
    for item, expected in (
        (_status(target, dirty=1), "dirty"),
        (_status(target, merged=False), "not merged"),
        (_status(target, locked="agent"), "locked"),
        (_status(target, dirty=None), "state unknown"),
        (_status(target, dirty=None, merged=None, bare=True), "bare worktree"),
    ):
        monkeypatch.setattr(
            lifecycle,
            "worktree_inventory",
            lambda root, run, which, item=item: [item],
        )
        ok, detail = lifecycle.cleanup_worktree(
            root,
            path=target,
            delete_branch=True,
            apply=True,
            run=lambda argv, cwd: CommandResult(0, ""),
            which=_which,
        )
        assert not ok and expected in detail


def test_cleanup_defaults_to_plan_only(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    target = tmp_path / "candidate"
    monkeypatch.setattr(
        lifecycle,
        "worktree_inventory",
        lambda root, run, which: [_status(target)],
    )
    commands: list[tuple[str, ...]] = []

    def run(argv: Any, cwd: Path) -> CommandResult:
        commands.append(tuple(argv))
        return CommandResult(0, "")

    ok, detail = lifecycle.cleanup_worktree(
        root,
        path=target,
        delete_branch=True,
        apply=False,
        run=run,
        which=_which,
    )

    assert ok
    assert "safe to remove" in detail and "--apply" in detail
    assert commands == []


def test_cleanup_apply_removes_worktree_and_merged_branch(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    target = tmp_path / "candidate"
    monkeypatch.setattr(
        lifecycle,
        "worktree_inventory",
        lambda root, run, which: [_status(target)],
    )
    commands: list[tuple[str, ...]] = []

    def run(argv: Any, cwd: Path) -> CommandResult:
        command = tuple(argv)
        commands.append(command)
        return CommandResult(0, "")

    ok, detail = lifecycle.cleanup_worktree(
        root,
        path=target,
        delete_branch=True,
        apply=True,
        run=run,
        which=_which,
    )

    assert ok and "removed" in detail
    assert ("/usr/bin/git", "worktree", "remove", str(target.resolve())) in commands
    assert ("/usr/bin/git", "branch", "-d", "feature/old") in commands


def test_cleanup_never_removes_protected_branch_worktree(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    target = tmp_path / "candidate"
    monkeypatch.setattr(
        lifecycle,
        "worktree_inventory",
        lambda root, run, which: [_status(target, branch="proof-of-concept")],
    )

    for delete_branch in (False, True):
        ok, detail = lifecycle.cleanup_worktree(
            root,
            path=target,
            delete_branch=delete_branch,
            apply=True,
            run=lambda argv, cwd: CommandResult(0, ""),
            which=_which,
        )

        assert not ok and "protected local branch" in detail
