"""Shared exact Phase 8 profile and snapshot fixtures."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from binnacle.domain.git import (
    GitHeadState,
    GitObjectAlgorithm,
    GitObjectId,
    GitRepositorySnapshot,
    ProtectedRemoteProfile,
    RegisteredGitRepositoryProfile,
    RepositorySafetyAssessment,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64
DIGEST_E = "e" * 64
DIGEST_F = "f" * 64
OID_SHA1 = "1" * 40


def repository_profile(root: Path, *, active: bool = True) -> RegisteredGitRepositoryProfile:
    remote = ProtectedRemoteProfile(
        profile_id="github-device",
        version="v1",
        scheme="ssh",
        host="github.com",
        port=22,
        repository_path="grammy-jiang/binnacle.git",
        service_user="git",
        allowed_destination_prefix="refs/heads/agent/",
        known_hosts_sha256=DIGEST_A,
        credential_reference_sha256=DIGEST_B,
        public_fingerprint="SHA256:device-public-key",
    )
    return RegisteredGitRepositoryProfile(
        repository_profile_id="binnacle-development",
        version="v1",
        workspace_id="development-workspace",
        workspace_profile_sha256=DIGEST_A,
        workspace_root=str(root),
        workspace_root_identity_sha256=DIGEST_B,
        workspace_mount_identity_sha256=DIGEST_C,
        git_directory=str(root / ".git"),
        git_directory_identity_sha256=DIGEST_D,
        common_directory=str(root / ".git"),
        common_directory_identity_sha256=DIGEST_E,
        object_format=GitObjectAlgorithm.SHA1,
        allowed_branch_prefix="refs/heads/agent/",
        protected_refs=("refs/heads/master",),
        git_executable="/usr/bin/git",
        git_executable_sha256=DIGEST_F,
        git_exec_path="/usr/lib/git-core",
        empty_home="/var/empty/binnacle-git",
        empty_hooks_directory="/etc/binnacle/git-empty-hooks",
        git_version_profile="git-v1",
        author_name="Binnacle Device",
        author_email="binnacle@example.invalid",
        committer_name="Binnacle Device",
        committer_email="binnacle@example.invalid",
        signing_reference_sha256=DIGEST_A,
        signing_public_fingerprint="OPENPGP:device-signing-key",
        remote=remote,
        safety_policy_version="git-safety-v1",
        active=active,
    )


def initialize_repository_shape(root: Path) -> RegisteredGitRepositoryProfile:
    git_directory = root / ".git"
    git_directory.mkdir(parents=True)
    (git_directory / "objects" / "info").mkdir(parents=True)
    (git_directory / "info").mkdir()
    (git_directory / "refs").mkdir()
    (git_directory / "hooks").mkdir()
    (git_directory / "config").write_text(
        """[core]
\trepositoryformatversion = 0
\tfilemode = true
\tbare = false
\tlogallrefupdates = true
[remote "origin"]
\turl = ssh://git@github.com:22/grammy-jiang/binnacle.git
\tfetch = +refs/heads/*:refs/remotes/origin/*
[branch "master"]
\tremote = origin
\tmerge = refs/heads/master
""",
        encoding="utf-8",
    )
    return repository_profile(root)


def safe_assessment(digest: str = DIGEST_F) -> RepositorySafetyAssessment:
    return RepositorySafetyAssessment(
        safe=True,
        reason_codes=(),
        repository_safety_sha256=digest,
        inspected_files=1,
        inspected_bytes=128,
    )


def repository_snapshot(
    profile: RegisteredGitRepositoryProfile,
    *,
    safety_sha256: str = DIGEST_F,
    complete: bool = True,
) -> GitRepositorySnapshot:
    return GitRepositorySnapshot(
        repository_profile_sha256=profile.profile_sha256,
        workspace_root_identity_sha256=profile.workspace_root_identity_sha256,
        workspace_mount_identity_sha256=profile.workspace_mount_identity_sha256,
        git_directory_identity_sha256=profile.git_directory_identity_sha256,
        common_directory_identity_sha256=profile.common_directory_identity_sha256,
        object_format=profile.object_format,
        head_state=GitHeadState.SYMBOLIC,
        head_ref="refs/heads/master",
        head_oid=GitObjectId(GitObjectAlgorithm.SHA1, OID_SHA1),
        index_tree_oid=GitObjectId(GitObjectAlgorithm.SHA1, "2" * 40),
        index_sha256=DIGEST_A,
        worktree_status_sha256=DIGEST_B,
        repository_safety_sha256=safety_sha256,
        staged_entries=0,
        unstaged_entries=0,
        untracked_entries=0,
        unmerged_entries=0,
        lock_files=(),
        in_progress_operations=(),
        complete=complete,
        captured_at=datetime(2026, 8, 13, 1, 2, 3, tzinfo=UTC),
    )
