"""Disposable local Git repositories for branch-sync regression tests."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from scripts import dev_branch_sync as sync


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in tuple(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    for key, value in {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "Fixture",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ALLOW_PROTOCOL": "file",
    }.items():
        monkeypatch.setenv(key, value)


def git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(path), *args], check=True, text=True, capture_output=True
    ).stdout.strip()


def commit(path: Path, filename: str = "upstream", content: str = "new\n") -> str:
    (path / filename).write_text(content)
    git(path, "add", filename)
    git(path, "commit", "-m", filename)
    return git(path, "rev-parse", "HEAD")


@dataclass
class Fixture:
    remote: Path
    seed: Path
    repo: Path
    wt: Path
    initial: str

    def advance(self) -> str:
        sha = commit(self.seed)
        git(self.seed, "push", "origin", "master")
        return sha

    def run(self, capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, Any]:
        argv = ["--repo", str(self.repo), "--worktree", str(self.wt)]
        argv += ["--branch", "feature/topic", "--session-lock-held", *args]
        code = sync.main(argv)
        return code, json.loads(capsys.readouterr().out)

    def unchanged(self, feature: str | None = None) -> None:
        assert git(self.repo, "rev-parse", "master") == self.initial
        assert git(self.wt, "rev-parse", "HEAD") == (feature or self.initial)


@pytest.fixture
def case(tmp_path: Path) -> Fixture:
    remote, seed, repo, worktree = (
        tmp_path / p for p in ("remote.git", "seed", "repo", "feature space")
    )
    git(tmp_path, "init", "--bare", "--initial-branch=master", str(remote))
    git(tmp_path, "init", "--initial-branch=master", str(seed))
    initial = commit(seed, "shared", "initial\n")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "origin", "master")
    git(tmp_path, "clone", "--single-branch", str(remote), str(repo))
    git(repo, "switch", "--detach")
    git(repo, "worktree", "add", "-b", "feature/topic", str(worktree))
    return Fixture(remote, seed, repo, worktree, initial)
