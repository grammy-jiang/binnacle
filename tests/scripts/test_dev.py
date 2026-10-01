"""Repository development bootstrap/doctor/worktree tooling."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from scripts import dev
from scripts import dev_worktrees as worktrees


def test_project_contract_parsers(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.uv]\nrequired-version = "==0.12.7"\n',
        encoding="utf-8",
    )
    (tmp_path / ".pre-commit-config.yaml").write_text(
        "default_install_hook_types: [pre-commit, pre-push]\n",
        encoding="utf-8",
    )
    assert dev.required_uv_version(tmp_path) == "0.12.7"
    assert dev.configured_hook_types(tmp_path) == (
        "pre-commit",
        "pre-push",
    )

    (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos: []\n",
        encoding="utf-8",
    )
    assert dev.configured_hook_types(tmp_path) == ("pre-commit",)


def test_bootstrap_commands_use_locked_sync_then_repository_pre_commit() -> None:
    assert dev.bootstrap_commands("/usr/bin/uv") == (
        ("/usr/bin/uv", "sync", "--locked", "--group", "dev"),
        (
            "/usr/bin/uv",
            "run",
            "--no-sync",
            "pre-commit",
            "install",
        ),
    )


def test_parse_worktree_porcelain_preserves_locked_and_detached() -> None:
    parsed = worktrees.parse_worktree_porcelain(
        """worktree /repo
HEAD aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
branch refs/heads/master

worktree /repo/agent
HEAD bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
branch refs/heads/feature/a
locked agent owns this worktree

worktree /repo/detached
HEAD cccccccccccccccccccccccccccccccccccccccc
detached
"""
    )
    assert [(item.path, item.branch) for item in parsed] == [
        (Path("/repo"), "master"),
        (Path("/repo/agent"), "feature/a"),
        (Path("/repo/detached"), None),
    ]
    assert parsed[1].locked == "agent owns this worktree"


def test_worktree_health_reports_independent_drift_signals() -> None:
    assert worktrees.worktree_health(
        branch="feature/old",
        merged_to_master=True,
        dirty_changes=2,
        upstream="gone",
        venv=False,
        lock="drift",
        locked="agent",
    ) == (
        "locked",
        "dirty",
        "upstream-gone",
        "merged",
        "no-venv",
        "lock-drift",
    )
    assert worktrees.worktree_health(
        branch="master",
        merged_to_master=True,
        dirty_changes=0,
        upstream="origin/master",
        venv=True,
        lock="current",
        locked=None,
    ) == ("ok",)


def _doctor_tree(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.uv]\nrequired-version = "==0.12.7"\n',
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (tmp_path / ".python-version").write_text(
        "3.13\n",
        encoding="utf-8",
    )
    (tmp_path / ".pre-commit-config.yaml").write_text(
        "default_install_hook_types: [pre-commit, pre-push]\n",
        encoding="utf-8",
    )
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o755)

    hooks = tmp_path / ".git-hooks"
    hooks.mkdir()
    pre_commit = hooks / "pre-commit"
    pre_commit.write_text("#!/bin/sh\n", encoding="utf-8")
    pre_commit.chmod(0o755)
    return python, hooks


def test_doctor_catches_missing_configured_pre_push_hook(
    tmp_path: Path,
) -> None:
    python, hooks = _doctor_tree(tmp_path)

    def which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"git", "uv", "rg"} else None

    def run(argv: Any, cwd: Path) -> dev.CommandResult:
        command = tuple(argv)
        if command == ("/usr/bin/uv", "--version"):
            return dev.CommandResult(0, "uv 0.12.7 (test)\n")
        if command == (
            "/usr/bin/git",
            "rev-parse",
            "--show-toplevel",
        ):
            return dev.CommandResult(0, f"{tmp_path}\n")
        if command == (
            "/usr/bin/git",
            "status",
            "--porcelain",
        ):
            return dev.CommandResult(0, "")
        if command == (
            "/usr/bin/uv",
            "lock",
            "--check",
            "--offline",
        ):
            return dev.CommandResult(0, "")
        if command == ("/usr/bin/rg", "--version"):
            return dev.CommandResult(0, "ripgrep 14.1.1\n")
        if command[0] == str(python):
            return dev.CommandResult(0, "3.13\n")
        if command[:3] == (
            "/usr/bin/git",
            "rev-parse",
            "--git-path",
        ):
            return dev.CommandResult(
                0,
                f"{hooks / Path(command[3]).name}\n",
            )
        raise AssertionError(command)

    checks = dev.doctor(tmp_path, run=run, which=which)
    by_name = {check.name: check for check in checks}
    assert by_name["hook:pre-commit"].status == "ok"
    assert by_name["hook:pre-push"].status == "fail"
    assert not [
        check
        for check in checks
        if check.status == "fail" and check.name != "hook:pre-push"
    ]

    pre_push = hooks / "pre-push"
    pre_push.write_text("#!/bin/sh\n", encoding="utf-8")
    pre_push.chmod(0o755)
    checks = dev.doctor(tmp_path, run=run, which=which)
    assert not [check for check in checks if check.status == "fail"]


def test_doctor_treats_a_dirty_checkout_as_warning_not_failure(
    tmp_path: Path,
) -> None:
    python, hooks = _doctor_tree(tmp_path)
    pre_push = hooks / "pre-push"
    pre_push.write_text("#!/bin/sh\n", encoding="utf-8")
    pre_push.chmod(0o755)

    def which(name: str) -> str | None:
        return f"/usr/bin/{name}"

    def run(argv: Any, cwd: Path) -> dev.CommandResult:
        command = tuple(argv)
        if command == ("/usr/bin/uv", "--version"):
            return dev.CommandResult(0, "uv 0.12.7\n")
        if command == (
            "/usr/bin/git",
            "rev-parse",
            "--show-toplevel",
        ):
            return dev.CommandResult(0, f"{tmp_path}\n")
        if command == (
            "/usr/bin/git",
            "status",
            "--porcelain",
        ):
            return dev.CommandResult(0, "?? local-note\n")
        if command == (
            "/usr/bin/uv",
            "lock",
            "--check",
            "--offline",
        ):
            return dev.CommandResult(0, "")
        if command == ("/usr/bin/rg", "--version"):
            return dev.CommandResult(0, "ripgrep 14.1.1\n")
        if command[0] == str(python):
            return dev.CommandResult(0, "3.13\n")
        if command[:3] == (
            "/usr/bin/git",
            "rev-parse",
            "--git-path",
        ):
            return dev.CommandResult(
                0,
                f"{hooks / Path(command[3]).name}\n",
            )
        raise AssertionError(command)

    checks = dev.doctor(tmp_path, run=run, which=which)
    dirty = next(check for check in checks if check.name == "working-tree")
    assert dirty.status == "warn"
    assert all(check.status != "fail" for check in checks)


def test_hook_executable_check_is_real(tmp_path: Path) -> None:
    hook = tmp_path / "hook"
    hook.write_text("#!/bin/sh\n", encoding="utf-8")
    hook.chmod(0o644)
    assert not os.access(hook, os.X_OK)
