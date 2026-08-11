"""Strict protected Phase 6 workspace-profile parsing tests."""

from __future__ import annotations

import dataclasses
import grp
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from binnacle.security.workspace_profile import (
    BOOTSTRAP_WORKSPACE_ROOT,
    RIPGREP_BINARY,
    WorkspaceProfile,
    WorkspaceProfileProtectionError,
    load_workspace_profile,
)


def _profile_values() -> dict[str, object]:
    return {
        "workspace_id": "binnacle-development",
        "profile_version": "1.0.0",
        "enabled": False,
        "root": BOOTSTRAP_WORKSPACE_ROOT,
        "protected_prefixes": [".git", ".private"],
    }


def _write_profile(path: Path) -> None:
    path.write_text(
        """
workspace_id = "binnacle-development"
profile_version = "1.0.0"
enabled = false
root = "/srv/binnacle-dev/repo"
protected_prefixes = [".private", ".git"]
""".strip(),
        encoding="utf-8",
    )


def _attempt_mutation(target: object, attribute: str, value: object) -> None:
    setattr(target, attribute, value)


def test_loader_uses_descriptor_bound_file_and_ignores_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_path = tmp_path / "workspace-profile.toml"
    _write_profile(profile_path)
    monkeypatch.setenv("BINNACLE_WORKSPACE_ROOT", "/tmp/untrusted")
    monkeypatch.setenv("BINNACLE_WORKSPACE_ENABLED", "true")

    profile = load_workspace_profile(profile_path, require_protected=False)

    assert profile.enabled is False
    assert profile.root == BOOTSTRAP_WORKSPACE_ROOT
    assert profile.protected_prefixes == (".git", ".private")
    assert profile.move_enabled is False
    assert profile.delete_enabled is False
    assert profile.search_process.executable == RIPGREP_BINARY

    with pytest.raises(WorkspaceProfileProtectionError):
        load_workspace_profile(profile_path)

    linked_profile = tmp_path / "linked-profile.toml"
    linked_profile.symlink_to(profile_path)
    with pytest.raises(WorkspaceProfileProtectionError):
        load_workspace_profile(linked_profile, require_protected=False)


def test_profile_is_frozen_and_summary_omits_protected_process_details() -> None:
    profile = WorkspaceProfile.model_validate(_profile_values())
    summary = profile.summary()
    summary_values = dataclasses.asdict(summary)

    assert len(profile.profile_sha256()) == 64
    assert summary.profile_sha256 == profile.profile_sha256()
    assert summary.root == BOOTSTRAP_WORKSPACE_ROOT
    assert summary.ripgrep_binary == RIPGREP_BINARY
    assert "protected_prefixes" not in summary_values
    assert "environment" not in summary_values
    assert ".private" not in repr(summary)
    assert "LANG=C" not in repr(summary)

    with pytest.raises(ValidationError, match="frozen"):
        _attempt_mutation(profile, "enabled", True)
    with pytest.raises(ValidationError, match="frozen"):
        _attempt_mutation(profile.search_process, "shell", True)


def test_profile_digest_is_canonical_over_effective_defaults() -> None:
    first_values = _profile_values()
    first_values["protected_prefixes"] = [".private", ".git"]
    second_values = _profile_values()
    second_values["protected_prefixes"] = [".git", ".private"]

    first = WorkspaceProfile.model_validate(first_values)
    second = WorkspaceProfile.model_validate(second_values)
    changed = WorkspaceProfile.model_validate({**second_values, "move_enabled": True})

    assert first.protected_prefixes == second.protected_prefixes
    assert first.profile_sha256() == second.profile_sha256()
    assert first.profile_sha256() == (
        "74a9d5d2b97911a02316e9ddf9c0f6af04f8de0d837429b1dc449fd797250a2a"
    )
    assert first.profile_sha256() != changed.profile_sha256()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("workspace_id", "not canonical"),
        ("profile_version", "version one"),
        ("root", "/tmp/repo"),
        ("allow_submounts", True),
        ("require_mount_id_verification", False),
        ("enabled", "false"),
        ("max_path_bytes", "4096"),
    ],
)
def test_profile_rejects_noncanonical_or_weakened_top_level_values(
    field: str,
    value: object,
) -> None:
    values = _profile_values()
    values[field] = value

    with pytest.raises(ValidationError):
        WorkspaceProfile.model_validate(values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("executable", "/tmp/rg"),
        ("working_directory", BOOTSTRAP_WORKSPACE_ROOT),
        ("mandatory_arguments", ["--json"]),
        ("environment", ["LANG=C", "LC_ALL=C", "HOME=/tmp"]),
        ("stdin_only", False),
        ("json_output", False),
        ("close_fds", False),
        ("shell", True),
        ("configuration_allowed", True),
        ("preprocessors_allowed", True),
        ("archive_search_allowed", True),
        ("helper_processes_allowed", True),
        ("workspace_discovery_authority", True),
        ("pcre2_allowed", True),
    ],
)
def test_profile_rejects_weakened_search_process_values(field: str, value: object) -> None:
    values = _profile_values()
    values["search_process"] = {field: value}

    with pytest.raises(ValidationError):
        WorkspaceProfile.model_validate(values)


@pytest.mark.parametrize(
    "prefixes",
    [
        [".private"],
        [".git", ".git"],
        [".git", ".git/config"],
        [".git", "/absolute"],
        [".git", "../escape"],
        [".git", "nested//empty"],
        [".git", "nested\\windows"],
        [".git", "C:drive"],
        [".git", "line\nbreak"],
        [".git", "e\N{COMBINING ACUTE ACCENT}"],
    ],
)
def test_profile_rejects_unsafe_or_redundant_protected_prefixes(
    prefixes: list[str],
) -> None:
    values = _profile_values()
    values["protected_prefixes"] = prefixes

    with pytest.raises(ValidationError):
        WorkspaceProfile.model_validate(values)


@pytest.mark.parametrize(
    "changes",
    [
        {"max_path_bytes": 4_097},
        {"max_path_depth": 65},
        {"max_file_mutation_bytes": 4 * 1_024 * 1_024 + 1},
        {"max_read_chunk_bytes": 1_024 * 1_024 + 1},
        {"max_list_entries": 4_097},
        {"max_search_files": 4_097},
        {"max_search_matches": 2_001},
        {"max_search_output_bytes": 1_024 * 1_024 + 1},
        {"max_search_preflight_bytes": 64 * 1_024 * 1_024 + 1},
        {"search_timeout_seconds": 5.1},
        {"search_timeout_seconds": "5.0"},
        {"search_preflight_timeout_seconds": float("nan")},
    ],
)
def test_profile_rejects_limits_outside_the_closed_bootstrap_envelope(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        WorkspaceProfile.model_validate({**_profile_values(), **changes})


def test_profile_forbids_unknown_top_level_and_process_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        WorkspaceProfile.model_validate({**_profile_values(), "root_from_environment": True})

    values = _profile_values()
    values["search_process"] = {"arbitrary_arguments": ["--pre", "helper"]}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        WorkspaceProfile.model_validate(values)


def test_loader_rejects_empty_oversized_and_nonregular_files(tmp_path: Path) -> None:
    empty = tmp_path / "empty.toml"
    empty.touch()
    with pytest.raises(WorkspaceProfileProtectionError, match="unsafe"):
        load_workspace_profile(empty, require_protected=False)

    oversized = tmp_path / "oversized.toml"
    oversized.write_bytes(b"x" * 65_537)
    with pytest.raises(WorkspaceProfileProtectionError, match="unsafe"):
        load_workspace_profile(oversized, require_protected=False)

    directory = tmp_path / "profile-directory"
    directory.mkdir()
    with pytest.raises(WorkspaceProfileProtectionError):
        load_workspace_profile(directory, require_protected=False)


def test_loader_closes_descriptor_when_metadata_lookup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_path = tmp_path / "workspace-profile.toml"
    _write_profile(profile_path)
    real_open = os.open
    real_close = os.close
    opened: list[int] = []
    closed: list[int] = []

    def tracked_open(path: Path, flags: int) -> int:
        descriptor = real_open(path, flags)
        opened.append(descriptor)
        return descriptor

    def fail_metadata_lookup(_descriptor: int) -> os.stat_result:
        raise OSError("synthetic fstat failure")

    def tracked_close(descriptor: int) -> None:
        closed.append(descriptor)
        real_close(descriptor)

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "fstat", fail_metadata_lookup)
    monkeypatch.setattr(os, "close", tracked_close)

    with pytest.raises(WorkspaceProfileProtectionError, match="unavailable"):
        load_workspace_profile(profile_path, require_protected=False)

    assert opened
    assert closed == opened


@pytest.mark.parametrize(
    ("uid", "gid", "mode", "accepted"),
    [
        (0, 1234, 0o640, True),
        (1, 1234, 0o640, False),
        (0, 1235, 0o640, False),
        (0, 1234, 0o600, False),
        (0, 1234, 0o644, False),
    ],
)
def test_protected_loader_requires_exact_root_binnacle_0640_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    uid: int,
    gid: int,
    mode: int,
    accepted: bool,
) -> None:
    profile_path = tmp_path / "workspace-profile.toml"
    _write_profile(profile_path)
    real = profile_path.stat()
    metadata = SimpleNamespace(
        st_dev=real.st_dev,
        st_ino=real.st_ino,
        st_mode=stat.S_IFREG | mode,
        st_size=real.st_size,
        st_uid=uid,
        st_gid=gid,
    )
    monkeypatch.setattr(os, "fstat", lambda _descriptor: metadata)
    monkeypatch.setattr(
        grp,
        "getgrnam",
        lambda _name: SimpleNamespace(gr_gid=1234),
    )

    if accepted:
        assert load_workspace_profile(profile_path).workspace_id == "binnacle-development"
    else:
        with pytest.raises(WorkspaceProfileProtectionError, match="root:binnacle"):
            load_workspace_profile(profile_path)
