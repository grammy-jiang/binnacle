from __future__ import annotations

import hashlib

import pytest
from tests.phase8_support import OID_SHA1

from binnacle.adapters.git.diff import GitDiffParseError, project_diff_result
from binnacle.adapters.git.status import GitStatusParseError, parse_porcelain_v2
from binnacle.domain.git import GitDiffMode, GitHeadState, GitObjectAlgorithm, GitStatusEntryKind

_MODE = "100644"
_SUBMODULE = "N..."
_OID_2 = "2" * 40
_OID_3 = "3" * 40


def test_parse_complete_symbolic_status_with_all_entry_shapes() -> None:
    content = (
        f"# branch.oid {OID_SHA1}\0"
        "# branch.head master\0"
        "# branch.upstream origin/master\0"
        "# branch.ab +2 -1\0"
        f"1 .M {_SUBMODULE} {_MODE} {_MODE} {_MODE} {OID_SHA1} {_OID_2} tracked file.txt\0"
        f"2 R. {_SUBMODULE} {_MODE} {_MODE} {_MODE} {OID_SHA1} {_OID_2} R100 renamed.txt\0"
        "old name.txt\0"
        f"u UU {_SUBMODULE} {_MODE} {_MODE} {_MODE} {_MODE} "
        f"{OID_SHA1} {_OID_2} {_OID_3} conflict.txt\0"
        "? untracked.txt\0"
        "! ignored.txt\0"
    ).encode()

    result = parse_porcelain_v2(
        content,
        object_format=GitObjectAlgorithm.SHA1,
        maximum_entries=10,
        maximum_bytes=10_000,
    )

    assert result.head_state is GitHeadState.SYMBOLIC
    assert result.head_ref == "refs/heads/master"
    assert result.head_oid is not None and result.head_oid.hex == OID_SHA1
    assert result.upstream_ref == "refs/remotes/origin/master"
    assert (result.ahead, result.behind) == (2, 1)
    assert tuple(entry.kind for entry in result.entries) == (
        GitStatusEntryKind.ORDINARY,
        GitStatusEntryKind.RENAMED_OR_COPIED,
        GitStatusEntryKind.UNMERGED,
        GitStatusEntryKind.UNTRACKED,
        GitStatusEntryKind.IGNORED,
    )
    assert result.entries[1].original_path == "old name.txt"
    assert result.raw_sha256 == hashlib.sha256(content).hexdigest()


def test_parse_detached_and_unborn_status() -> None:
    detached = parse_porcelain_v2(
        f"# branch.oid {OID_SHA1}\0# branch.head (detached)\0".encode(),
        object_format=GitObjectAlgorithm.SHA1,
        maximum_entries=1,
        maximum_bytes=1_000,
    )
    assert detached.head_state is GitHeadState.DETACHED
    assert detached.head_ref is None

    unborn = parse_porcelain_v2(
        b"# branch.oid (initial)\0# branch.head agent/new\0",
        object_format=GitObjectAlgorithm.SHA1,
        maximum_entries=1,
        maximum_bytes=1_000,
    )
    assert unborn.head_state is GitHeadState.UNBORN
    assert unborn.head_oid is None
    assert unborn.head_ref == "refs/heads/agent/new"


@pytest.mark.parametrize(
    "content,match",
    [
        (b"", "complete"),
        (b"# branch.head master", "complete"),
        (b"# branch.head master\0", "complete HEAD"),
        (b"# branch.head\0", "header"),
        (b"# unknown value\0# branch.head master\0", "unexpected header"),
        (b"# branch.head master\0# branch.head main\0", "repeats"),
        (b"# branch.oid (initial)\0# branch.oid (initial)\0# branch.head main\0", "repeats"),
        (b"# branch.oid bad\0# branch.head master\0", "HEAD object"),
        (b"# branch.head (detached)\0", "lacks an object"),
        (
            b"# branch.oid (initial)\0# branch.head master\0# branch.ab +1 -0\0",
            "lack an upstream",
        ),
        (
            b"# branch.head master\0# branch.upstream origin/master\0# branch.ab 1 -0\0",
            "ahead/behind",
        ),
        (b"# branch.head master\0x unsupported\0", "unsupported record"),
        (b"# branch.head master\x001 malformed\0", "ordinary"),
        (b"# branch.head master\x002 malformed\0", "renamed"),
        (b"# branch.head master\0u malformed\0", "unmerged"),
        (
            (
                f"# branch.oid {OID_SHA1}\0# branch.head master\0"
                f"2 R. N... {_MODE} {_MODE} {_MODE} {OID_SHA1} {_OID_2} R100 new\0"
            ).encode(),
            "original",
        ),
        (b"# branch.head master\0? \xff\0", "not valid UTF-8"),
        (b"# branch.oid (initial)\0# branch.head master\0? same\0? same\0", "repeats"),
        (
            f"# branch.oid {OID_SHA1}\0# branch.head master\0"
            "1 .M BAD 100644 100644 100644 "
            f"{OID_SHA1} {_OID_2} tracked.txt\0".encode(),
            "metadata",
        ),
        (
            f"# branch.oid {OID_SHA1}\0# branch.head master\0"
            f"2 R. N... 100644 100644 100644 {OID_SHA1} {_OID_2} C100 renamed\0"
            "old\0".encode(),
            "score",
        ),
        (
            f"# branch.oid {OID_SHA1}\0# branch.head master\0"
            f"u XX N... 100644 100644 100644 100644 {OID_SHA1} {_OID_2} {_OID_3} p\0".encode(),
            "codes",
        ),
    ],
)
def test_status_parser_fails_closed_on_malformed_output(content: bytes, match: str) -> None:
    with pytest.raises(GitStatusParseError, match=match):
        parse_porcelain_v2(
            content,
            object_format=GitObjectAlgorithm.SHA1,
            maximum_entries=10,
            maximum_bytes=10_000,
        )


def test_status_parser_enforces_bounds_and_exact_arguments() -> None:
    content = b"# branch.oid (initial)\0# branch.head master\0? one\0? two\0"
    with pytest.raises(GitStatusParseError, match="entry ceiling"):
        parse_porcelain_v2(
            content,
            object_format=GitObjectAlgorithm.SHA1,
            maximum_entries=1,
            maximum_bytes=1_000,
        )
    with pytest.raises(GitStatusParseError, match="byte ceiling"):
        parse_porcelain_v2(
            content,
            object_format=GitObjectAlgorithm.SHA1,
            maximum_entries=10,
            maximum_bytes=1,
        )
    with pytest.raises(ValueError, match="positive"):
        parse_porcelain_v2(
            content,
            object_format=GitObjectAlgorithm.SHA1,
            maximum_entries=0,
            maximum_bytes=1,
        )


def test_diff_projection_is_bounded_and_explicitly_marks_prefixes() -> None:
    content = (
        b"diff --git a/a.txt b/a.txt\n"
        b"index 111..222 100644\n"
        b"--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"
        b"diff --git a/image.bin b/image.bin\n"
        b"GIT binary patch\nliteral 0\nHcmV?d00001\n"
    )
    result = project_diff_result(
        content,
        mode=GitDiffMode.WORKTREE_TO_INDEX,
        maximum_bytes=10_000,
        maximum_files=10,
        truncated=True,
    )
    assert result.file_count == 2
    assert result.binary_file_count == 1
    assert result.truncated
    assert result.raw_sha256 == hashlib.sha256(content).hexdigest()

    without_newline = project_diff_result(
        b"one line",
        mode=GitDiffMode.INDEX_TO_HEAD,
        maximum_bytes=100,
        maximum_files=1,
    )
    assert without_newline.line_count == 1


def test_diff_projection_rejects_excess_or_contradictory_results() -> None:
    with pytest.raises(ValueError, match="positive"):
        project_diff_result(
            b"",
            mode=GitDiffMode.WORKTREE_TO_INDEX,
            maximum_bytes=0,
            maximum_files=1,
        )
    with pytest.raises(GitDiffParseError, match="byte ceiling"):
        project_diff_result(
            b"too long",
            mode=GitDiffMode.WORKTREE_TO_INDEX,
            maximum_bytes=1,
            maximum_files=1,
        )
    with pytest.raises(GitDiffParseError, match="file ceiling"):
        project_diff_result(
            b"diff --git a/a b/a\ndiff --git a/b b/b\n",
            mode=GitDiffMode.WORKTREE_TO_INDEX,
            maximum_bytes=100,
            maximum_files=1,
        )
    with pytest.raises(GitDiffParseError, match="contradictory"):
        project_diff_result(
            b"GIT binary patch\n",
            mode=GitDiffMode.WORKTREE_TO_INDEX,
            maximum_bytes=100,
            maximum_files=1,
        )
