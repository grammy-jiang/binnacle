from __future__ import annotations

from dataclasses import replace

import pytest

from binnacle.domain.workspace import (
    ExactTextReplacement,
    WorkspaceError,
    WorkspaceObjectIdentity,
    WorkspaceObjectKind,
    apply_exact_text_patch,
    is_protected_workspace_path,
    normalize_workspace_path,
    object_version,
    require_content_path_allowed,
    workspace_path_sha256,
)

DIGEST = "a" * 64


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "../escape", "a//b", "a/./b", "a\\b", "a\nb", ".binnacle-stage"],
)
def test_workspace_path_normalizer_rejects_escape_and_reserved_forms(path: str) -> None:
    with pytest.raises(WorkspaceError):
        normalize_workspace_path(path)


def test_workspace_paths_are_nfc_relative_and_protected_by_component() -> None:
    assert normalize_workspace_path("src/binnacle/main.py") == "src/binnacle/main.py"
    assert normalize_workspace_path("", allow_root=True) == ""
    assert is_protected_workspace_path(".git/config")
    assert not is_protected_workspace_path(".github/workflows/python.yml")
    assert is_protected_workspace_path("private/key", additional_roots=("private",))
    with pytest.raises(WorkspaceError, match="protected"):
        require_content_path_allowed(".git/HEAD")


def test_workspace_path_digest_has_a_fixed_domain_separated_vector() -> None:
    assert workspace_path_sha256("src/module.py") == (
        "8a7fe92f49f42a88b5ef0928adc716d0fb0303914d6aee61d2bb0ddb6cb11288"
    )
    assert workspace_path_sha256("src/module.py") != workspace_path_sha256("src/other.py")


def _identity() -> WorkspaceObjectIdentity:
    return WorkspaceObjectIdentity(
        workspace_id="workspace",
        profile_sha256=DIGEST,
        root_identity_sha256=DIGEST,
        mount_identity_sha256=DIGEST,
        relative_path="src/module.py",
        kind=WorkspaceObjectKind.REGULAR_FILE,
        device=1,
        inode=2,
        mode=0o100644,
        size=12,
        modified_ns=123,
        link_count=1,
        content_sha256=DIGEST,
    )


def test_object_version_binds_mount_content_and_link_count() -> None:
    identity = _identity()
    token = object_version(identity)
    assert len(token) == 64
    assert object_version(replace(identity, mount_identity_sha256="b" * 64)) != token
    assert object_version(replace(identity, content_sha256="b" * 64)) != token
    assert object_version(replace(identity, link_count=2)) != token


def test_only_registered_root_directory_can_use_empty_relative_path() -> None:
    root = replace(
        _identity(),
        relative_path="",
        kind=WorkspaceObjectKind.DIRECTORY,
        content_sha256=None,
    )
    assert len(object_version(root)) == 64
    with pytest.raises(WorkspaceError, match="relative POSIX"):
        replace(root, kind=WorkspaceObjectKind.REGULAR_FILE)


def test_patch_matches_original_exactly_once_and_rejects_overlap() -> None:
    assert (
        apply_exact_text_patch(
            b"alpha beta gamma",
            (ExactTextReplacement("alpha", "A"), ExactTextReplacement("gamma", "G")),
        )
        == b"A beta G"
    )
    with pytest.raises(WorkspaceError, match="exactly once"):
        apply_exact_text_patch(b"same same", (ExactTextReplacement("same", "new"),))
    with pytest.raises(WorkspaceError, match="overlap"):
        apply_exact_text_patch(
            b"abcdef",
            (ExactTextReplacement("abcd", "x"), ExactTextReplacement("cdef", "y")),
        )


def test_patch_rejects_binary_and_oversized_result() -> None:
    with pytest.raises(WorkspaceError, match="UTF-8"):
        apply_exact_text_patch(b"\xff", (ExactTextReplacement("x", "y"),))
    with pytest.raises(WorkspaceError, match="exceeds"):
        apply_exact_text_patch(
            b"a",
            (ExactTextReplacement("a", "long"),),
            maximum_bytes=3,
        )
