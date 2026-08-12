from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar, cast

import pytest
from tests.phase8_support import (
    DIGEST_A,
    DIGEST_B,
    DIGEST_C,
    DIGEST_D,
    DIGEST_F,
    OID_SHA1,
    repository_profile,
    repository_snapshot,
    safe_assessment,
)

from binnacle.adapters.git.cli import ClosedGitExecutionPlanBuilder
from binnacle.domain.git import (
    GitCredentialAction,
    GitDiffMode,
    GitDiffResult,
    GitError,
    GitExecutionPlan,
    GitHeadState,
    GitObjectAlgorithm,
    GitObjectId,
    GitOperationKind,
    GitReadPermit,
    GitStatusEntry,
    GitStatusEntryKind,
    GitStatusResult,
    MainIndexPublicationState,
    ProtectedRemoteProfile,
    RepositorySafetyAssessment,
    canonical_sha256,
    canonical_timestamp,
    normalize_development_branch,
    require_full_local_branch_ref,
)
from binnacle.ports import git as git_ports

_T = TypeVar("_T")


def _replace_dynamic(instance: _T, changes: dict[str, object]) -> _T:
    return cast(_T, replace(cast(Any, instance), **changes))


def test_git_object_ids_are_full_algorithm_tagged_values() -> None:
    sha1 = GitObjectId(GitObjectAlgorithm.SHA1, OID_SHA1)
    sha256 = GitObjectId(GitObjectAlgorithm.SHA256, "2" * 64)

    assert sha1.to_wire() == {"algorithm": "sha1", "hex": OID_SHA1}
    assert GitObjectId.from_wire(sha256.to_wire()) == sha256
    assert GitObjectAlgorithm.SHA1.hexadecimal_length == 40
    assert GitObjectAlgorithm.SHA256.hexadecimal_length == 64

    for value in ("1" * 39, "A" * 40, "g" * 40):
        with pytest.raises(GitError, match="full lowercase"):
            GitObjectId(GitObjectAlgorithm.SHA1, value)
    for wire in (
        None,
        {"algorithm": "sha1"},
        {"algorithm": 1, "hex": OID_SHA1},
        {"algorithm": "sha512", "hex": OID_SHA1},
    ):
        with pytest.raises(GitError):
            GitObjectId.from_wire(wire)


def test_git_ports_are_explicit_and_default_disabled() -> None:
    assert git_ports.__all__ == [
        "GitReadExecutionDispatcher",
        "GitReadRecoveryBarrier",
        "GitRepositoryInspector",
        "GitRepositoryProfileValidator",
    ]


@pytest.mark.parametrize(
    "value",
    [
        "master",
        "refs/tags/v1",
        "refs/heads/a..b",
        "refs/heads/a.lock",
        "refs/heads/a@{b",
        "refs/heads/a b",
        "refs/heads//a",
        "refs/heads/.hidden",
        "refs/heads/a\\b",
        "refs/heads/é",
        "refs/heads/a/",
        "refs/heads/a./b",
        "refs/heads/a\x7f",
    ],
)
def test_full_local_branch_ref_rejects_ambiguous_or_special_names(value: str) -> None:
    with pytest.raises(GitError, match="local branch ref"):
        require_full_local_branch_ref(value)


def test_development_branch_normalization_is_namespace_bounded() -> None:
    assert (
        normalize_development_branch("agent/phase-08", allowed_prefix="refs/heads/agent/")
        == "refs/heads/agent/phase-08"
    )
    assert (
        normalize_development_branch(
            "refs/heads/agent/phase-08", allowed_prefix="refs/heads/agent/"
        )
        == "refs/heads/agent/phase-08"
    )
    for value in ("master", "agent/e\N{COMBINING ACUTE ACCENT}", "agent/\0bad"):
        with pytest.raises(GitError):
            normalize_development_branch(value, allowed_prefix="refs/heads/agent/")
    with pytest.raises(GitError, match="prefix"):
        normalize_development_branch("agent/test", allowed_prefix="refs/heads/agent")


def test_protected_remote_profile_rejects_redirectable_authority() -> None:
    base = ProtectedRemoteProfile(
        profile_id="github-device",
        version="v1",
        scheme="ssh",
        host="github.com",
        port=22,
        repository_path="owner/repo.git",
        service_user="git",
        allowed_destination_prefix="refs/heads/agent/",
        known_hosts_sha256=DIGEST_A,
        credential_reference_sha256=DIGEST_B,
        public_fingerprint="SHA256:key",
    )
    assert base.host == "github.com"
    invalid_changes: tuple[dict[str, object], ...] = (
        {"scheme": "https"},
        {"host": "GitHub.com"},
        {"port": 0},
        {"repository_path": "/owner/repo.git"},
        {"repository_path": "owner/../repo.git"},
        {"service_user": ""},
        {"service_user": "git@example.com"},
        {"known_hosts_sha256": "bad"},
        {"allowed_destination_prefix": "refs/heads/agent"},
        {"public_fingerprint": ""},
        {"public_fingerprint": "SHA256:key\nredirect"},
    )
    for changes in invalid_changes:
        with pytest.raises(GitError):
            _replace_dynamic(base, changes)


def test_repository_profile_is_exact_and_inactive_by_default(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    profile = repository_profile(root, active=False)

    assert not profile.active
    assert len(profile.profile_sha256) == 64
    assert profile.require_branch_allowed("agent/change") == "refs/heads/agent/change"
    for branch in ("master", "other/change"):
        with pytest.raises(GitError):
            profile.require_branch_allowed(branch)

    invalid_changes: tuple[dict[str, object], ...] = (
        {"workspace_profile_sha256": "bad"},
        {"git_directory": str(root / "other")},
        {"common_directory": str(root / "common")},
        {"workspace_root": f"{root}/"},
        {"protected_refs": ()},
        {"protected_refs": ("refs/heads/main",)},
        {"protected_refs": ("refs/heads/master", "refs/heads/master")},
        {"author_name": "line\nbreak"},
        {"author_name": "line\rbreak"},
        {"maximum_status_entries": 0},
        {"maximum_diff_bytes": 1},
        {"maximum_object_bytes": 1},
        {"maximum_operation_seconds": 0},
    )
    for changes in invalid_changes:
        with pytest.raises(GitError):
            _replace_dynamic(profile, changes)


def test_snapshot_models_detached_unborn_and_clean_state(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    profile = repository_profile(root)
    snapshot = repository_snapshot(profile)

    assert snapshot.is_clean
    assert len(snapshot.repository_state_binding_sha256) == 64
    dirty = replace(snapshot, untracked_entries=1)
    assert not dirty.is_clean
    detached = replace(snapshot, head_state=GitHeadState.DETACHED, head_ref=None)
    assert detached.head_oid is not None
    unborn = replace(
        snapshot,
        head_state=GitHeadState.UNBORN,
        head_oid=None,
        index_tree_oid=None,
    )
    assert unborn.head_ref == "refs/heads/master"
    unavailable = replace(
        snapshot,
        complete=False,
        head_state=GitHeadState.UNAVAILABLE,
        head_ref=None,
        head_oid=None,
    )
    assert not unavailable.is_clean

    with pytest.raises(GitError, match="HEAD state"):
        replace(snapshot, head_state=GitHeadState.DETACHED)
    with pytest.raises(GitError, match="cannot omit HEAD"):
        replace(
            snapshot,
            head_state=GitHeadState.UNAVAILABLE,
            head_ref=None,
            head_oid=None,
        )
    with pytest.raises(GitError, match="object format"):
        replace(snapshot, index_tree_oid=GitObjectId(GitObjectAlgorithm.SHA256, "3" * 64))
    with pytest.raises(GitError, match="cannot be negative"):
        replace(snapshot, staged_entries=-1)
    with pytest.raises(GitError, match="unique and sorted"):
        replace(snapshot, lock_files=("z.lock", "a.lock"))
    with pytest.raises(GitError, match="timezone"):
        replace(snapshot, captured_at=datetime(2026, 8, 13))


def test_status_and_diff_result_contracts() -> None:
    entry = GitStatusEntry(
        kind=GitStatusEntryKind.RENAMED_OR_COPIED,
        index_status="R",
        worktree_status=".",
        path="new name.txt",
        original_path="old name.txt",
    )
    status = GitStatusResult(
        object_format=GitObjectAlgorithm.SHA1,
        head_state=GitHeadState.SYMBOLIC,
        head_ref="refs/heads/master",
        head_oid=GitObjectId(GitObjectAlgorithm.SHA1, OID_SHA1),
        upstream_ref="refs/remotes/origin/master",
        ahead=1,
        behind=2,
        entries=(entry,),
        complete=True,
        raw_sha256=DIGEST_A,
    )
    assert len(status.status_sha256) == 64

    diff = GitDiffResult(
        mode=GitDiffMode.WORKTREE_TO_INDEX,
        byte_count=10,
        line_count=1,
        file_count=1,
        binary_file_count=0,
        truncated=False,
        raw_sha256=DIGEST_B,
    )
    assert len(diff.result_sha256) == 64

    with pytest.raises(GitError, match="rename shape"):
        replace(entry, original_path=None)
    with pytest.raises(GitError, match="status code"):
        replace(entry, index_status="X")
    with pytest.raises(GitError, match="ahead/behind"):
        replace(status, ahead=None)
    with pytest.raises(GitError, match="negative"):
        replace(status, ahead=-1)
    with pytest.raises(GitError, match="binary count"):
        replace(diff, binary_file_count=2)


def test_read_permit_and_canonical_timestamp_are_stable() -> None:
    expires_at = datetime(2026, 8, 13, 3, 4, 5, tzinfo=UTC)
    permit = GitReadPermit(
        request_id="request-1",
        application_generation=1,
        content_guard_epoch=2,
        development_session_id="session-1",
        development_session_state_version=3,
        repository_profile_sha256=DIGEST_A,
        repository_state_binding_sha256=DIGEST_B,
        expires_at=expires_at,
    )
    assert permit.permit_sha256 == permit.permit_sha256
    assert canonical_timestamp(expires_at) == "2026-08-13T03:04:05.000000+00:00"
    assert canonical_sha256({"state": MainIndexPublicationState.PENDING})
    with pytest.raises(GitError, match="positive"):
        replace(permit, content_guard_epoch=0)
    with pytest.raises(GitError, match="timezone"):
        replace(permit, expires_at=datetime(2026, 8, 13))
    with pytest.raises(GitError, match="timezone"):
        canonical_timestamp(datetime(2026, 8, 13))
    with pytest.raises(TypeError, match="unsupported canonical"):
        canonical_sha256({1, 2})


def test_closed_plan_builder_produces_noninteractive_read_plans(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    profile = repository_profile(root)
    snapshot = repository_snapshot(profile)
    safety = safe_assessment()
    builder = ClosedGitExecutionPlanBuilder(profile)

    status = builder.status(snapshot, safety)
    assert status.operation is GitOperationKind.STATUS
    assert status.argv[-2:] == ("--no-renames", "-z")
    assert ("GIT_ATTR_NOSYSTEM", "1") in status.environment
    assert ("GIT_OPTIONAL_LOCKS", "0") in status.environment
    assert not status.network_allowed
    assert status.credential_action is GitCredentialAction.NONE
    assert not status.command_run_visible

    diff = builder.diff(
        snapshot,
        safety,
        mode=GitDiffMode.WORKTREE_TO_INDEX,
        paths=("docs/design.md",),
    )
    assert diff.argv[-2:] == ("--", "docs/design.md")
    assert "--no-ext-diff" in diff.argv
    assert "--no-textconv" in diff.argv

    cached = builder.diff(snapshot, safety, mode=GitDiffMode.INDEX_TO_HEAD)
    assert cached.argv[-3:-1] == ("--cached", OID_SHA1)

    object_diff = builder.diff(
        snapshot,
        safety,
        mode=GitDiffMode.OBJECT_TO_OBJECT,
        old_oid=GitObjectId(GitObjectAlgorithm.SHA1, "3" * 40),
        new_oid=GitObjectId(GitObjectAlgorithm.SHA1, "4" * 40),
    )
    assert object_diff.argv[-3:-1] == ("3" * 40, "4" * 40)

    branch = builder.branch_create(
        snapshot,
        safety,
        branch="agent/phase-08",
        start_oid=GitObjectId(GitObjectAlgorithm.SHA1, OID_SHA1),
    )
    assert branch.operation is GitOperationKind.BRANCH_CREATE
    assert branch.argv[-3:] == ("refs/heads/agent/phase-08", OID_SHA1, "0" * 40)
    assert ("GIT_OPTIONAL_LOCKS", "1") in branch.environment


def test_plan_builder_rejects_stale_unsafe_or_unreviewed_inputs(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    profile = repository_profile(root)
    snapshot = repository_snapshot(profile)
    safety = safe_assessment()
    builder = ClosedGitExecutionPlanBuilder(profile)

    unsafe = RepositorySafetyAssessment(
        safe=False,
        reason_codes=("hooks_present",),
        repository_safety_sha256=DIGEST_F,
        inspected_files=1,
        inspected_bytes=1,
    )
    cases = (
        (ClosedGitExecutionPlanBuilder(replace(profile, active=False)), snapshot, safety),
        (builder, replace(snapshot, complete=False), safety),
        (builder, replace(snapshot, repository_profile_sha256=DIGEST_D), safety),
        (builder, snapshot, unsafe),
        (builder, snapshot, replace(safety, repository_safety_sha256=DIGEST_C)),
    )
    for candidate, candidate_snapshot, candidate_safety in cases:
        with pytest.raises(GitError):
            candidate.status(candidate_snapshot, candidate_safety)

    with pytest.raises(GitError, match="cannot carry"):
        builder.diff(
            snapshot,
            safety,
            mode=GitDiffMode.WORKTREE_TO_INDEX,
            old_oid=GitObjectId(GitObjectAlgorithm.SHA1, OID_SHA1),
        )
    with pytest.raises(GitError, match="requires two"):
        builder.diff(snapshot, safety, mode=GitDiffMode.OBJECT_TO_OBJECT)
    with pytest.raises(GitError, match="object format"):
        builder.diff(
            snapshot,
            safety,
            mode=GitDiffMode.OBJECT_TO_OBJECT,
            old_oid=GitObjectId(GitObjectAlgorithm.SHA256, "3" * 64),
            new_oid=GitObjectId(GitObjectAlgorithm.SHA256, "4" * 64),
        )
    for paths in (("../escape",), (".git/config",), ("b", "a"), ("a", "a")):
        with pytest.raises(GitError, match="path selection"):
            builder.diff(snapshot, safety, mode=GitDiffMode.WORKTREE_TO_INDEX, paths=paths)
    with pytest.raises(GitError, match="count"):
        builder.diff(
            snapshot,
            safety,
            mode=GitDiffMode.WORKTREE_TO_INDEX,
            paths=tuple(f"file-{index}" for index in range(257)),
        )


def test_execution_plan_rejects_credentials_on_reads_and_open_environments() -> None:
    base = GitExecutionPlan(
        operation=GitOperationKind.STATUS,
        executable="/usr/bin/git",
        argv=("git", "status"),
        environment=(("LC_ALL", "C"),),
        working_directory="/srv/binnacle/repo",
        repository_profile_sha256=DIGEST_A,
        repository_state_binding_sha256=DIGEST_B,
        network_allowed=False,
        credential_action=GitCredentialAction.NONE,
        credential_reference_sha256=None,
        maximum_output_bytes=1_024,
        timeout_seconds=1,
    )
    assert len(base.plan_sha256) == 64
    invalid_changes: tuple[dict[str, object], ...] = (
        {"executable": "git"},
        {"argv": ()},
        {"argv": ("git", "bad\narg")},
        {"environment": (("AWS_SECRET_ACCESS_KEY", "secret"),)},
        {"environment": (("LC_ALL", "C"), ("LC_ALL", "C"))},
        {"network_allowed": True},
        {
            "credential_action": GitCredentialAction.FETCH,
            "credential_reference_sha256": None,
        },
        {"credential_reference_sha256": DIGEST_A},
        {"maximum_output_bytes": 1},
        {"timeout_seconds": 0},
        {"command_run_visible": True},
    )
    for changes in invalid_changes:
        with pytest.raises(GitError):
            _replace_dynamic(base, changes)
