from __future__ import annotations

import os
from pathlib import Path

import pytest
from tests.phase8_support import initialize_repository_shape, repository_profile

from binnacle.adapters.git.config_validator import BoundedGitRepositoryProfileValidator


def test_safe_normal_repository_produces_stable_safety_digest(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    profile = initialize_repository_shape(root)
    (root / ".git" / "hooks" / "pre-commit.sample").write_text("sample", encoding="utf-8")
    (root / "nested").mkdir()
    (root / "nested" / ".gitattributes").write_text("*.txt text\n", encoding="utf-8")
    validator = BoundedGitRepositoryProfileValidator()

    first = validator.validate(profile)
    second = validator.validate(profile)

    assert first.safe
    assert first.reason_codes == ()
    assert first.repository_safety_sha256 == second.repository_safety_sha256
    assert first.inspected_files == 2
    assert first.inspected_bytes > 0


@pytest.mark.parametrize(
    "fragment,reason",
    [
        ("\n[include]\n\tpath = /tmp/attacker\n", "forbidden_config"),
        ("\n[credential]\n\thelper = !steal\n", "forbidden_config"),
        ("\n[core]\n\thooksPath = hooks\n", "forbidden_config"),
        ("\n[core]\n\tfsmonitor = !helper\n", "forbidden_config"),
        ("\n[alias]\n\tpwn = !helper\n", "forbidden_config"),
        ('\n[filter "evil"]\n\tprocess = helper\n', "forbidden_config"),
        ('\n[diff "evil"]\n\ttextconv = helper\n', "forbidden_config"),
        ('\n[merge "evil"]\n\tdriver = helper\n', "forbidden_config"),
        ('\n[url "ssh://evil/"]\n\tinsteadOf = ssh://github.com/\n', "forbidden_config"),
        ("\n[http]\n\tproxy = http://evil\n", "forbidden_config"),
        ("\n[unknown]\n\tvalue = true\n", "unsupported_config"),
        ("\n[extensions]\n\tpartialClone = origin\n", "promisor_repository"),
        ("\n[extensions]\n\tworktreeConfig = true\n", "linked_worktrees_present"),
        ('\n[remote "extra"]\n\tpromisor = true\n', "promisor_repository"),
        ('\n[remote "extra"]\n\tuploadpack = helper\n', "forbidden_config"),
        ("\n[branch]\n\tmerge = main\n", "unsupported_config"),
        ('\n[branch "bad"]\n\tmerge = main\n', "unsupported_config"),
    ],
)
def test_repository_config_helpers_and_indeterminate_keys_are_rejected(
    tmp_path: Path,
    fragment: str,
    reason: str,
) -> None:
    root = tmp_path / "repo"
    profile = initialize_repository_shape(root)
    config = root / ".git" / "config"
    config.write_text(config.read_text(encoding="utf-8") + fragment, encoding="utf-8")

    assessment = BoundedGitRepositoryProfileValidator().validate(profile)

    assert not assessment.safe
    assert reason in assessment.reason_codes


def test_remote_and_object_format_must_match_protected_profile(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    profile = initialize_repository_shape(root)
    config = root / ".git" / "config"
    original = config.read_text(encoding="utf-8")
    config.write_text(original.replace("github.com:22", "example.com:22"), encoding="utf-8")
    remote = BoundedGitRepositoryProfileValidator().validate(profile)
    assert "remote_mismatch" in remote.reason_codes

    config.write_text(original + "\n[extensions]\n\tobjectFormat = sha256\n", encoding="utf-8")
    object_format = BoundedGitRepositoryProfileValidator().validate(profile)
    assert "object_format_mismatch" in object_format.reason_codes


@pytest.mark.parametrize(
    "relative_path,reason",
    [
        (".git/shallow", "shallow_repository"),
        (".git/info/grafts", "grafts_present"),
        (".git/info/sparse-checkout", "sparse_repository"),
        (".git/objects/info/alternates", "alternate_object_store"),
        (".git/objects/info/http-alternates", "alternate_object_store"),
    ],
)
def test_unsupported_repository_marker_files_are_rejected(
    tmp_path: Path,
    relative_path: str,
    reason: str,
) -> None:
    root = tmp_path / "repo"
    profile = initialize_repository_shape(root)
    marker = root / relative_path
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("marker", encoding="utf-8")

    assessment = BoundedGitRepositoryProfileValidator().validate(profile)

    assert reason in assessment.reason_codes


@pytest.mark.parametrize(
    "relative_path,reason",
    [
        (".git/modules/submodule", "submodules_present"),
        (".git/refs/replace/object", "replace_refs_present"),
        (".git/worktrees/linked", "linked_worktrees_present"),
    ],
)
def test_unsupported_repository_marker_directories_are_rejected(
    tmp_path: Path,
    relative_path: str,
    reason: str,
) -> None:
    root = tmp_path / "repo"
    profile = initialize_repository_shape(root)
    marker = root / relative_path
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("marker", encoding="utf-8")

    assessment = BoundedGitRepositoryProfileValidator().validate(profile)

    assert reason in assessment.reason_codes


@pytest.mark.parametrize(
    "relative_path,content,reason",
    [
        (".gitattributes", "*.bin filter=lfs diff=lfs\n", "unsafe_attributes"),
        ("nested/.gitattributes", "*.txt merge=custom\n", "unsafe_attributes"),
        (".gitmodules", '[submodule "x"]\npath=x\n', "submodules_present"),
        (".lfsconfig", "[lfs]\nurl=https://example.invalid\n", "lfs_present"),
    ],
)
def test_worktree_helper_surfaces_are_rejected_at_any_depth(
    tmp_path: Path,
    relative_path: str,
    content: str,
    reason: str,
) -> None:
    root = tmp_path / "repo"
    profile = initialize_repository_shape(root)
    control_file = root / relative_path
    control_file.parent.mkdir(parents=True, exist_ok=True)
    control_file.write_text(content, encoding="utf-8")

    assessment = BoundedGitRepositoryProfileValidator().validate(profile)

    assert reason in assessment.reason_codes


def test_git_info_attributes_are_hashed_and_cannot_select_helpers(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    profile = initialize_repository_shape(root)
    validator = BoundedGitRepositoryProfileValidator()
    before = validator.validate(profile)
    attributes = root / ".git" / "info" / "attributes"
    attributes.write_text("*.txt text\n", encoding="utf-8")

    safe = validator.validate(profile)
    assert safe.safe
    assert safe.repository_safety_sha256 != before.repository_safety_sha256

    attributes.write_text("*.txt diff=external-driver\n", encoding="utf-8")
    unsafe = validator.validate(profile)
    assert "unsafe_attributes" in unsafe.reason_codes


def test_hooks_and_worktree_config_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    profile = initialize_repository_shape(root)
    (root / ".git" / "hooks" / "pre-push").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / ".git" / "config.worktree").write_text("[core]\n\tbare = false\n", encoding="utf-8")

    assessment = BoundedGitRepositoryProfileValidator().validate(profile)

    assert {"hooks_present", "linked_worktrees_present"} <= set(assessment.reason_codes)


def test_missing_malformed_and_non_regular_config_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    profile = initialize_repository_shape(root)
    config = root / ".git" / "config"

    config.unlink()
    assert "config_missing" in BoundedGitRepositoryProfileValidator().validate(profile).reason_codes

    config.write_bytes(b"\xff")
    assert (
        "config_malformed" in BoundedGitRepositoryProfileValidator().validate(profile).reason_codes
    )

    config.write_text("key-without-section = value\n", encoding="utf-8")
    assert (
        "config_malformed" in BoundedGitRepositoryProfileValidator().validate(profile).reason_codes
    )

    config.unlink()
    target = root / "config-target"
    target.write_text("[core]\nbare=false\n", encoding="utf-8")
    config.symlink_to(target)
    assert (
        "repository_shape" in BoundedGitRepositoryProfileValidator().validate(profile).reason_codes
    )


def test_hardlinked_symlinked_and_disappearing_control_files_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    profile = initialize_repository_shape(root)
    attributes = root / ".gitattributes"
    attributes.write_text("*.txt text\n", encoding="utf-8")
    os.link(attributes, root / "attributes-copy")
    hardlinked = BoundedGitRepositoryProfileValidator().validate(profile)
    assert "repository_shape" in hardlinked.reason_codes

    attributes.unlink()
    attributes.symlink_to(root / "attributes-copy")
    symlinked = BoundedGitRepositoryProfileValidator().validate(profile)
    assert "unsafe_attributes" in symlinked.reason_codes

    attributes.unlink()
    attributes.write_text("*.txt text\n", encoding="utf-8")
    original_open = os.open
    disappeared = False

    def disappear_before_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal disappeared
        if path == ".gitattributes" and dir_fd is not None and not disappeared:
            attributes.unlink()
            disappeared = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", disappear_before_open)
    raced = BoundedGitRepositoryProfileValidator().validate(profile)
    assert raced.reason_codes == ("repository_shape",)


def test_root_shape_and_all_inspection_limits_fail_closed(tmp_path: Path) -> None:
    missing_root = tmp_path / "missing"
    missing = BoundedGitRepositoryProfileValidator().validate(repository_profile(missing_root))
    assert missing.reason_codes == ("repository_shape",)

    root = tmp_path / "repo"
    profile = initialize_repository_shape(root)
    (root / "one").mkdir()
    (root / "two").mkdir()
    tree_limit = BoundedGitRepositoryProfileValidator(maximum_tree_entries=1).validate(profile)
    assert "inspection_limit" in tree_limit.reason_codes

    file_limit = BoundedGitRepositoryProfileValidator(maximum_files=1).validate(profile)
    (root / ".gitattributes").write_text("*.txt text\n", encoding="utf-8")
    file_limit = BoundedGitRepositoryProfileValidator(maximum_files=1).validate(profile)
    assert "inspection_limit" in file_limit.reason_codes

    byte_limit = BoundedGitRepositoryProfileValidator(maximum_bytes=8).validate(profile)
    assert "inspection_limit" in byte_limit.reason_codes

    with pytest.raises(ValueError, match="positive"):
        BoundedGitRepositoryProfileValidator(maximum_files=0)


def test_tree_and_hook_enumeration_stop_at_the_configured_bound(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    profile = initialize_repository_shape(root)
    for index in range(20):
        (root / f"directory-{index:02d}").mkdir()
        (root / ".git" / "hooks" / f"sample-{index:02d}.sample").write_text(
            "sample",
            encoding="utf-8",
        )

    assessment = BoundedGitRepositoryProfileValidator(maximum_tree_entries=3).validate(profile)

    assert "inspection_limit" in assessment.reason_codes


def test_git_directory_and_marker_directory_type_confusion_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    profile = repository_profile(root)
    (root / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    assessment = BoundedGitRepositoryProfileValidator().validate(profile)
    assert "repository_shape" in assessment.reason_codes

    (root / ".git").unlink()
    profile = initialize_repository_shape(root)
    (root / ".git" / "worktrees").write_text("not a directory", encoding="utf-8")
    confused = BoundedGitRepositoryProfileValidator().validate(profile)
    assert "linked_worktrees_present" in confused.reason_codes


def test_invalid_utf8_attributes_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    profile = initialize_repository_shape(root)
    (root / ".gitattributes").write_bytes(b"*.txt diff=\xff\n")

    assessment = BoundedGitRepositoryProfileValidator().validate(profile)

    assert "unsafe_attributes" in assessment.reason_codes
