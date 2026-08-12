"""Strict parser for the bounded ``git status --porcelain=v2 -z`` profile."""

from __future__ import annotations

import hashlib
import re
from typing import Final

from binnacle.domain.git import (
    GitError,
    GitHeadState,
    GitObjectAlgorithm,
    GitObjectId,
    GitStatusEntry,
    GitStatusEntryKind,
    GitStatusResult,
)


class GitStatusParseError(GitError):
    """The official Git output is malformed or outside the frozen profile."""


_MODE_RE: Final = re.compile(r"[0-7]{6}\Z")
_SUBMODULE_RE: Final = re.compile(r"(?:N\.\.\.|S[.C][.M][.U])\Z")
_ORDINARY_STATUS: Final = frozenset(".MTADRC")
_UNMERGED_STATUS: Final = frozenset({"DD", "AU", "UD", "UA", "DU", "AA", "UU"})


def parse_porcelain_v2(
    content: bytes,
    *,
    object_format: GitObjectAlgorithm,
    maximum_entries: int,
    maximum_bytes: int,
) -> GitStatusResult:
    if min(maximum_entries, maximum_bytes) < 1:
        raise ValueError("Git status parser limits must be positive")
    if len(content) > maximum_bytes:
        raise GitStatusParseError("Git status output exceeds the reviewed byte ceiling")
    if not content or not content.endswith(b"\0"):
        raise GitStatusParseError("Git status output is not complete NUL-delimited data")

    records = content[:-1].split(b"\0")
    head_oid: GitObjectId | None = None
    head_name: str | None = None
    upstream_ref: str | None = None
    ahead: int | None = None
    behind: int | None = None
    entries: list[GitStatusEntry] = []
    head_oid_seen = False
    index = 0
    while index < len(records):
        raw_record = records[index]
        index += 1
        if raw_record.startswith(b"# "):
            key, value = _header(raw_record)
            if key == "branch.oid":
                if head_oid_seen:
                    raise GitStatusParseError("Git status repeats the HEAD object")
                head_oid_seen = True
                if value != "(initial)":
                    head_oid = _object_id(object_format, value)
            elif key == "branch.head":
                if head_name is not None:
                    raise GitStatusParseError("Git status repeats the HEAD name")
                head_name = value
            elif key == "branch.upstream":
                if upstream_ref is not None:
                    raise GitStatusParseError("Git status repeats the upstream ref")
                upstream_ref = _upstream_ref(value)
            elif key == "branch.ab":
                if ahead is not None or behind is not None:
                    raise GitStatusParseError("Git status repeats ahead/behind facts")
                ahead, behind = _ahead_behind(value)
            else:
                raise GitStatusParseError("Git status includes an unexpected header")
            continue

        entry, consumes_original = _entry(raw_record, object_format)
        if consumes_original:
            if index >= len(records):
                raise GitStatusParseError("renamed Git status entry lacks its original path")
            original_path = _decode(records[index], "Git status original path")
            index += 1
            entry = GitStatusEntry(
                kind=entry.kind,
                index_status=entry.index_status,
                worktree_status=entry.worktree_status,
                path=entry.path,
                original_path=original_path,
            )
        entries.append(entry)
        if len(entries) > maximum_entries:
            raise GitStatusParseError("Git status output exceeds the reviewed entry ceiling")

    if head_name is None:
        raise GitStatusParseError("Git status output lacks a HEAD name")
    if head_name == "(detached)":
        head_state = GitHeadState.DETACHED
        head_ref = None
        if head_oid is None:
            raise GitStatusParseError("detached Git HEAD lacks an object")
    else:
        head_ref = f"refs/heads/{head_name}"
        head_state = GitHeadState.SYMBOLIC if head_oid is not None else GitHeadState.UNBORN
    if not head_oid_seen:
        raise GitStatusParseError("Git status output lacks complete HEAD facts")
    if (ahead is not None or behind is not None) and upstream_ref is None:
        raise GitStatusParseError("Git status ahead/behind facts lack an upstream")
    if len({entry.path for entry in entries}) != len(entries):
        raise GitStatusParseError("Git status output repeats a repository path")
    try:
        return GitStatusResult(
            object_format=object_format,
            head_state=head_state,
            head_ref=head_ref,
            head_oid=head_oid,
            upstream_ref=upstream_ref,
            ahead=ahead,
            behind=behind,
            entries=tuple(entries),
            complete=True,
            raw_sha256=hashlib.sha256(content).hexdigest(),
        )
    except GitError as exc:
        raise GitStatusParseError("Git status output violates the normalized contract") from exc


def _header(record: bytes) -> tuple[str, str]:
    text = _decode(record[2:], "Git status header")
    try:
        key, value = text.split(" ", 1)
    except ValueError as exc:
        raise GitStatusParseError("Git status header is malformed") from exc
    if not value:
        raise GitStatusParseError("Git status header value is empty")
    return key, value


def _entry(
    record: bytes,
    object_format: GitObjectAlgorithm,
) -> tuple[GitStatusEntry, bool]:
    if record.startswith(b"1 "):
        fields = _decode(record, "ordinary Git status entry").split(" ", 8)
        if len(fields) != 9 or len(fields[1]) != 2:
            raise GitStatusParseError("ordinary Git status entry is malformed")
        _validate_entry_metadata(
            fields,
            object_format=object_format,
            mode_indexes=(3, 4, 5),
            oid_indexes=(6, 7),
        )
        if any(value not in _ORDINARY_STATUS for value in fields[1]):
            raise GitStatusParseError("ordinary Git status codes are invalid")
        return (
            GitStatusEntry(
                kind=GitStatusEntryKind.ORDINARY,
                index_status=fields[1][0],
                worktree_status=fields[1][1],
                path=fields[8],
            ),
            False,
        )
    if record.startswith(b"2 "):
        fields = _decode(record, "renamed Git status entry").split(" ", 9)
        if len(fields) != 10 or len(fields[1]) != 2:
            raise GitStatusParseError("renamed Git status entry is malformed")
        _validate_entry_metadata(
            fields,
            object_format=object_format,
            mode_indexes=(3, 4, 5),
            oid_indexes=(6, 7),
        )
        score = fields[8]
        if (
            fields[1][0] not in {"R", "C"}
            or fields[1][1] not in _ORDINARY_STATUS
            or len(score) not in {2, 3, 4}
            or score[0] != fields[1][0]
            or not score[1:].isdigit()
            or not 0 <= int(score[1:]) <= 100
        ):
            raise GitStatusParseError("renamed Git status score is invalid")
        return (
            GitStatusEntry(
                kind=GitStatusEntryKind.RENAMED_OR_COPIED,
                index_status=fields[1][0],
                worktree_status=fields[1][1],
                path=fields[9],
                original_path="placeholder",
            ),
            True,
        )
    if record.startswith(b"u "):
        fields = _decode(record, "unmerged Git status entry").split(" ", 10)
        if len(fields) != 11 or len(fields[1]) != 2:
            raise GitStatusParseError("unmerged Git status entry is malformed")
        _validate_entry_metadata(
            fields,
            object_format=object_format,
            mode_indexes=(3, 4, 5, 6),
            oid_indexes=(7, 8, 9),
        )
        if fields[1] not in _UNMERGED_STATUS:
            raise GitStatusParseError("unmerged Git status codes are invalid")
        return (
            GitStatusEntry(
                kind=GitStatusEntryKind.UNMERGED,
                index_status=fields[1][0],
                worktree_status=fields[1][1],
                path=fields[10],
            ),
            False,
        )
    if record.startswith((b"? ", b"! ")):
        text = _decode(record, "untracked Git status entry")
        ignored = text[0] == "!"
        return (
            GitStatusEntry(
                kind=GitStatusEntryKind.IGNORED if ignored else GitStatusEntryKind.UNTRACKED,
                index_status="!" if ignored else "?",
                worktree_status="!" if ignored else "?",
                path=text[2:],
            ),
            False,
        )
    raise GitStatusParseError("Git status includes an unsupported record type")


def _object_id(algorithm: GitObjectAlgorithm, value: str) -> GitObjectId:
    try:
        return GitObjectId(algorithm, value)
    except GitError as exc:
        raise GitStatusParseError("Git status HEAD object is invalid") from exc


def _validate_entry_metadata(
    fields: list[str],
    *,
    object_format: GitObjectAlgorithm,
    mode_indexes: tuple[int, ...],
    oid_indexes: tuple[int, ...],
) -> None:
    if _SUBMODULE_RE.fullmatch(fields[2]) is None or any(
        _MODE_RE.fullmatch(fields[index]) is None for index in mode_indexes
    ):
        raise GitStatusParseError("Git status entry metadata is invalid")
    for index in oid_indexes:
        try:
            GitObjectId(object_format, fields[index])
        except GitError as exc:
            raise GitStatusParseError("Git status entry object ID is invalid") from exc


def _upstream_ref(value: str) -> str:
    if value.startswith("refs/"):
        return value
    if not value or value.startswith(("/", ".")) or "/" not in value:
        raise GitStatusParseError("Git status upstream is not an exact remote branch")
    return f"refs/remotes/{value}"


def _ahead_behind(value: str) -> tuple[int, int]:
    parts = value.split(" ")
    if len(parts) != 2 or not parts[0].startswith("+") or not parts[1].startswith("-"):
        raise GitStatusParseError("Git status ahead/behind facts are malformed")
    try:
        ahead = int(parts[0][1:])
        behind = int(parts[1][1:])
    except ValueError as exc:
        raise GitStatusParseError("Git status ahead/behind facts are malformed") from exc
    if min(ahead, behind) < 0:
        raise GitStatusParseError("Git status ahead/behind facts are negative")
    if max(ahead, behind) > 9_223_372_036_854_775_807:
        raise GitStatusParseError("Git status ahead/behind facts exceed the reviewed bound")
    return ahead, behind


def _decode(value: bytes, label: str) -> str:
    try:
        return value.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise GitStatusParseError(f"{label} is not valid UTF-8") from exc


__all__ = ["GitStatusParseError", "parse_porcelain_v2"]
