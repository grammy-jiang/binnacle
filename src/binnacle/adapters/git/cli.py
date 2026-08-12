"""Closed Git CLI plan construction; this module never starts a process."""

from __future__ import annotations

from binnacle.domain.git import (
    GitCredentialAction,
    GitDiffMode,
    GitError,
    GitExecutionPlan,
    GitObjectId,
    GitOperationKind,
    GitRepositorySnapshot,
    RegisteredGitRepositoryProfile,
    RepositorySafetyAssessment,
)
from binnacle.domain.workspace import WorkspaceError, require_content_path_allowed


class ClosedGitExecutionPlanBuilder:
    """Build shell-free, noninteractive plans for internal Phase 7 dispatch."""

    def __init__(self, profile: RegisteredGitRepositoryProfile) -> None:
        self._profile = profile

    def status(
        self,
        snapshot: GitRepositorySnapshot,
        safety: RepositorySafetyAssessment,
    ) -> GitExecutionPlan:
        self._require_ready(snapshot, safety)
        return self._plan(
            operation=GitOperationKind.STATUS,
            snapshot=snapshot,
            argv=(
                *self._read_prefix(),
                "status",
                "--porcelain=v2",
                "--branch",
                "--untracked-files=all",
                "--ignored=no",
                "--no-renames",
                "-z",
            ),
            maximum_output_bytes=min(
                20_000_000,
                max(1_024, self._profile.maximum_status_entries * 1_024),
            ),
        )

    def diff(
        self,
        snapshot: GitRepositorySnapshot,
        safety: RepositorySafetyAssessment,
        *,
        mode: GitDiffMode,
        paths: tuple[str, ...] = (),
        old_oid: GitObjectId | None = None,
        new_oid: GitObjectId | None = None,
    ) -> GitExecutionPlan:
        self._require_ready(snapshot, safety)
        normalized_paths = _normalize_paths(paths)
        revision_arguments: tuple[str, ...]
        if mode is GitDiffMode.WORKTREE_TO_INDEX:
            if old_oid is not None or new_oid is not None:
                raise GitError("worktree diff cannot carry object revisions")
            revision_arguments = ()
        elif mode is GitDiffMode.INDEX_TO_HEAD:
            if old_oid is not None or new_oid is not None:
                raise GitError("index-to-HEAD diff cannot carry object revisions")
            if snapshot.head_oid is None:
                raise GitError("index-to-HEAD diff requires an existing HEAD object")
            revision_arguments = ("--cached", snapshot.head_oid.hex)
        else:
            if old_oid is None or new_oid is None:
                raise GitError("object diff requires two full object IDs")
            self._require_object_format(old_oid)
            self._require_object_format(new_oid)
            revision_arguments = (old_oid.hex, new_oid.hex)
        return self._plan(
            operation=GitOperationKind.DIFF,
            snapshot=snapshot,
            argv=(
                *self._read_prefix(),
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
                "--no-color",
                "--full-index",
                "--binary",
                *revision_arguments,
                "--",
                *normalized_paths,
            ),
            maximum_output_bytes=self._profile.maximum_diff_bytes,
        )

    def branch_create(
        self,
        snapshot: GitRepositorySnapshot,
        safety: RepositorySafetyAssessment,
        *,
        branch: str,
        start_oid: GitObjectId,
    ) -> GitExecutionPlan:
        self._require_ready(snapshot, safety)
        full_ref = self._profile.require_branch_allowed(branch)
        self._require_object_format(start_oid)
        zero = "0" * self._profile.object_format.hexadecimal_length
        return self._plan(
            operation=GitOperationKind.BRANCH_CREATE,
            snapshot=snapshot,
            argv=(
                *self._write_prefix(),
                "update-ref",
                "--no-deref",
                "-m",
                "binnacle phase-08 branch create",
                full_ref,
                start_oid.hex,
                zero,
            ),
            maximum_output_bytes=64_000,
        )

    def _read_prefix(self) -> tuple[str, ...]:
        return (*self._common_prefix(), "--no-optional-locks")

    def _write_prefix(self) -> tuple[str, ...]:
        return self._common_prefix()

    def _common_prefix(self) -> tuple[str, ...]:
        return (
            "git",
            "--no-pager",
            "--literal-pathspecs",
            "-c",
            f"core.hooksPath={self._profile.empty_hooks_directory}",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "maintenance.auto=false",
            "-c",
            "fetch.writeCommitGraph=false",
            "-c",
            "gc.auto=0",
            "-c",
            "protocol.allow=never",
            "-c",
            "color.ui=false",
        )

    def _plan(
        self,
        *,
        operation: GitOperationKind,
        snapshot: GitRepositorySnapshot,
        argv: tuple[str, ...],
        maximum_output_bytes: int,
    ) -> GitExecutionPlan:
        environment = (
            ("GIT_CONFIG_GLOBAL", "/dev/null"),
            ("GIT_CONFIG_NOSYSTEM", "1"),
            ("GIT_CONFIG_SYSTEM", "/dev/null"),
            ("GIT_EXEC_PATH", self._profile.git_exec_path),
            ("GIT_NO_REPLACE_OBJECTS", "1"),
            ("GIT_OPTIONAL_LOCKS", "0" if operation in _READ_OPERATIONS else "1"),
            ("GIT_PAGER", "cat"),
            ("GIT_PROTOCOL_FROM_USER", "0"),
            ("GIT_TERMINAL_PROMPT", "0"),
            ("HOME", self._profile.empty_home),
            ("LC_ALL", "C"),
            ("PATH", "/usr/bin:/bin"),
            ("XDG_CONFIG_HOME", self._profile.empty_home),
        )
        return GitExecutionPlan(
            operation=operation,
            executable=self._profile.git_executable,
            argv=argv,
            environment=environment,
            working_directory=self._profile.workspace_root,
            repository_profile_sha256=self._profile.profile_sha256,
            repository_state_binding_sha256=snapshot.repository_state_binding_sha256,
            network_allowed=False,
            credential_action=GitCredentialAction.NONE,
            credential_reference_sha256=None,
            maximum_output_bytes=maximum_output_bytes,
            timeout_seconds=self._profile.maximum_operation_seconds,
        )

    def _require_ready(
        self,
        snapshot: GitRepositorySnapshot,
        safety: RepositorySafetyAssessment,
    ) -> None:
        if not self._profile.active:
            raise GitError("Git repository profile is not active")
        if not safety.safe:
            raise GitError("repository helper surface is unsafe")
        if safety.repository_safety_sha256 != snapshot.repository_safety_sha256:
            raise GitError("repository safety assessment is stale")
        expected = (
            self._profile.profile_sha256,
            self._profile.workspace_root_identity_sha256,
            self._profile.workspace_mount_identity_sha256,
            self._profile.git_directory_identity_sha256,
            self._profile.common_directory_identity_sha256,
            self._profile.object_format,
        )
        observed = (
            snapshot.repository_profile_sha256,
            snapshot.workspace_root_identity_sha256,
            snapshot.workspace_mount_identity_sha256,
            snapshot.git_directory_identity_sha256,
            snapshot.common_directory_identity_sha256,
            snapshot.object_format,
        )
        if observed != expected or not snapshot.complete:
            raise GitError("repository snapshot is stale or incomplete")

    def _require_object_format(self, oid: GitObjectId) -> None:
        if oid.algorithm is not self._profile.object_format:
            raise GitError("Git object ID conflicts with the registered object format")


_READ_OPERATIONS = frozenset({GitOperationKind.STATUS, GitOperationKind.DIFF})


def _normalize_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    if len(paths) > 256:
        raise GitError("Git path selection exceeds the reviewed count")
    normalized: list[str] = []
    for path in paths:
        try:
            normalized.append(require_content_path_allowed(path))
        except WorkspaceError as exc:
            raise GitError("Git path selection is outside the workspace content boundary") from exc
    if tuple(sorted(set(normalized))) != tuple(normalized):
        raise GitError("Git path selection must be unique and sorted")
    return tuple(normalized)


__all__ = ["ClosedGitExecutionPlanBuilder"]
