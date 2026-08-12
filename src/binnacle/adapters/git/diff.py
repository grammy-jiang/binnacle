"""Bounded metadata projection for an immutable Git diff payload."""

from __future__ import annotations

import hashlib

from binnacle.domain.git import GitDiffMode, GitDiffResult, GitError


class GitDiffParseError(GitError):
    """A diff payload violates the reviewed output bounds."""


def project_diff_result(
    content: bytes,
    *,
    mode: GitDiffMode,
    maximum_bytes: int,
    maximum_files: int,
    truncated: bool = False,
) -> GitDiffResult:
    """Project bounded counters; callers retain the exact bytes in Phase 4 payload storage."""

    if min(maximum_bytes, maximum_files) < 1:
        raise ValueError("Git diff projection limits must be positive")
    if len(content) > maximum_bytes:
        raise GitDiffParseError("Git diff output exceeds the reviewed byte ceiling")
    file_count = sum(line.startswith(b"diff --git ") for line in content.splitlines())
    if file_count > maximum_files:
        raise GitDiffParseError("Git diff output exceeds the reviewed file ceiling")
    binary_file_count = sum(
        line == b"GIT binary patch" or line.startswith(b"Binary files ")
        for line in content.splitlines()
    )
    try:
        return GitDiffResult(
            mode=mode,
            byte_count=len(content),
            line_count=content.count(b"\n") + bool(content and not content.endswith(b"\n")),
            file_count=file_count,
            binary_file_count=binary_file_count,
            truncated=truncated,
            raw_sha256=hashlib.sha256(content).hexdigest(),
        )
    except GitError as exc:
        raise GitDiffParseError("Git diff projection is contradictory") from exc


__all__ = ["GitDiffParseError", "project_diff_result"]
