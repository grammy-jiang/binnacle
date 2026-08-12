from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from tests.phase8_support import repository_profile, repository_snapshot

from binnacle.adapters.git.cli import ClosedGitExecutionPlanBuilder
from binnacle.adapters.git.config_validator import BoundedGitRepositoryProfileValidator
from binnacle.adapters.git.diff import project_diff_result
from binnacle.adapters.git.status import parse_porcelain_v2
from binnacle.domain.git import GitDiffMode, GitHeadState, GitObjectAlgorithm, GitObjectId


@pytest.fixture
def real_repository(tmp_path: Path) -> tuple[Path, str]:
    executable = shutil.which("git")
    if executable is None:
        pytest.skip("official Git CLI is unavailable")
    root = tmp_path / "repository"
    root.mkdir()
    subprocess.run(
        [executable, "init", "--initial-branch=master", str(root)],
        check=True,
        capture_output=True,
    )
    (root / "tracked.txt").write_text("original\n", encoding="utf-8")
    environment = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Binnacle Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Binnacle Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    }
    subprocess.run([executable, "add", "tracked.txt"], cwd=root, env=environment, check=True)
    subprocess.run(
        [executable, "commit", "-m", "initial"],
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            executable,
            "remote",
            "add",
            "origin",
            "ssh://git@github.com:22/grammy-jiang/binnacle.git",
        ],
        cwd=root,
        check=True,
    )
    return root, executable


def test_closed_status_plan_is_read_only_and_strictly_parseable(
    real_repository: tuple[Path, str],
) -> None:
    root, executable = real_repository
    empty_home = root.parent / "empty-home"
    empty_hooks = root.parent / "empty-hooks"
    empty_home.mkdir()
    empty_hooks.mkdir()
    profile = replace(
        repository_profile(root),
        git_executable=executable,
        git_exec_path=_git_exec_path(executable),
        empty_home=str(empty_home),
        empty_hooks_directory=str(empty_hooks),
    )
    safety = BoundedGitRepositoryProfileValidator().validate(profile)
    assert safety.safe
    head = _head_oid(executable, root)
    snapshot = replace(
        repository_snapshot(profile, safety_sha256=safety.repository_safety_sha256),
        head_oid=head,
        index_tree_oid=head,
    )
    plan = ClosedGitExecutionPlanBuilder(profile).status(snapshot, safety)
    index = root / ".git" / "index"
    index_before = index.read_bytes()

    completed = subprocess.run(
        plan.argv,
        executable=plan.executable,
        cwd=plan.working_directory,
        env=dict(plan.environment),
        check=True,
        capture_output=True,
        timeout=plan.timeout_seconds,
    )
    status = parse_porcelain_v2(
        completed.stdout,
        object_format=profile.object_format,
        maximum_entries=profile.maximum_status_entries,
        maximum_bytes=plan.maximum_output_bytes,
    )

    assert status.head_state is GitHeadState.SYMBOLIC
    assert status.head_ref == "refs/heads/master"
    assert status.head_oid == head
    assert status.entries == ()
    assert index.read_bytes() == index_before


def test_closed_diff_plan_disables_helpers_and_projects_exact_bytes(
    real_repository: tuple[Path, str],
) -> None:
    root, executable = real_repository
    empty_home = root.parent / "empty-home"
    empty_hooks = root.parent / "empty-hooks"
    empty_home.mkdir()
    empty_hooks.mkdir()
    profile = replace(
        repository_profile(root),
        git_executable=executable,
        git_exec_path=_git_exec_path(executable),
        empty_home=str(empty_home),
        empty_hooks_directory=str(empty_hooks),
    )
    safety = BoundedGitRepositoryProfileValidator().validate(profile)
    head = _head_oid(executable, root)
    snapshot = replace(
        repository_snapshot(profile, safety_sha256=safety.repository_safety_sha256),
        head_oid=head,
        index_tree_oid=head,
    )
    (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
    plan = ClosedGitExecutionPlanBuilder(profile).diff(
        snapshot,
        safety,
        mode=GitDiffMode.WORKTREE_TO_INDEX,
        paths=("tracked.txt",),
    )

    completed = subprocess.run(
        plan.argv,
        executable=plan.executable,
        cwd=plan.working_directory,
        env=dict(plan.environment),
        check=True,
        capture_output=True,
        timeout=plan.timeout_seconds,
    )
    result = project_diff_result(
        completed.stdout,
        mode=GitDiffMode.WORKTREE_TO_INDEX,
        maximum_bytes=profile.maximum_diff_bytes,
        maximum_files=16,
    )

    assert result.file_count == 1
    assert result.binary_file_count == 0
    assert not result.truncated
    assert b"-original" in completed.stdout
    assert b"+changed" in completed.stdout


def _git_exec_path(executable: str) -> str:
    return subprocess.run(
        [executable, "--exec-path"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _head_oid(executable: str, root: Path) -> GitObjectId:
    value = subprocess.run(
        [executable, "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return GitObjectId(GitObjectAlgorithm.SHA1, value)
