"""OS5 canonical alias regressions; escapes remain denied."""

from pathlib import Path

import pytest

from binnacle.config import RootsSettings
from binnacle.errors import CodedToolError
from binnacle.features.files.paths import nearby_hint, resolve_path


def test_allowed_root_alias_resolves_relative_and_absolute_paths(tmp_path: Path):
    actual = tmp_path / "real-root"
    actual.mkdir()
    (actual / "file.txt").write_text("hello")
    alias = tmp_path / "alias-root"
    alias.symlink_to(actual, target_is_directory=True)
    roots = RootsSettings(default_root=alias, extra_roots=())

    assert resolve_path("file.txt", roots=roots) == actual / "file.txt"
    assert resolve_path(str(alias / "file.txt"), roots=roots) == actual / "file.txt"
    assert nearby_hint(alias, roots=roots) == (
        f" Files in {alias}: file.txt. Use list_files for more."
    )


def test_allowed_alias_does_not_allow_escaping_symlinks_or_parent(tmp_path: Path):
    actual = tmp_path / "real-root"
    actual.mkdir()
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "secret").write_text("secret")
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    (actual / "escape").symlink_to(outside, target_is_directory=True)
    roots = RootsSettings(default_root=alias, extra_roots=())

    for candidate in ("escape/secret", "../private/secret", str(outside / "secret")):
        with pytest.raises(CodedToolError) as exc:
            resolve_path(candidate, roots=roots)
        assert exc.value.telemetry_code == "path_outside_root"
    assert nearby_hint(alias / "escape", roots=roots) == ""


def test_allowed_extra_root_alias_and_missing_target(tmp_path: Path):
    root = tmp_path / "regular"
    root.mkdir()
    actual = tmp_path / "other"
    actual.mkdir()
    alias = tmp_path / "other-alias"
    alias.symlink_to(actual, target_is_directory=True)
    roots = RootsSettings(default_root=root, extra_roots=(alias,))
    assert resolve_path(str(alias / "not-yet-created"), roots=roots) == (
        actual / "not-yet-created"
    )
    assert resolve_path("missing", roots=roots) == root / "missing"
