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


def test_alias_switch_after_resolution_cannot_redirect_canonical_file(tmp_path: Path):
    """The returned canonical path is not tied to the user's mutable alias."""
    real = tmp_path / "real"
    real.mkdir()
    (real / "source.txt").write_text("inside")
    secret = tmp_path / "outside"
    secret.mkdir()
    (secret / "source.txt").write_text("outside")
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    roots = RootsSettings(default_root=alias, extra_roots=())

    authorized = resolve_path("source.txt", roots=roots)
    assert authorized == real / "source.txt"
    alias.unlink()
    alias.symlink_to(secret, target_is_directory=True)

    # The previously approved canonical name does not follow that alias.
    assert authorized.read_text() == "inside"
    with pytest.raises(CodedToolError) as exc:
        resolve_path("source.txt", roots=roots)
    assert exc.value.telemetry_code == "path_outside_root"


def test_symlink_chain_canonicalizes_inside_and_denies_escape(tmp_path: Path):
    actual = tmp_path / "actual"
    actual.mkdir()
    (actual / "sub").mkdir()
    link_a = tmp_path / "link-a"
    link_b = tmp_path / "link-b"
    link_b.symlink_to(actual, target_is_directory=True)
    link_a.symlink_to(link_b, target_is_directory=True)
    roots = RootsSettings(default_root=link_a, extra_roots=())
    assert resolve_path("sub/../sub/new.txt", roots=roots) == (actual / "sub/new.txt")
    outside = tmp_path / "outside"
    outside.mkdir()
    (actual / "sub" / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(CodedToolError) as exc:
        resolve_path("sub/escape/secret", roots=roots)
    assert exc.value.telemetry_code == "path_outside_root"


def test_path_root_resolution_error_retains_original_error_code(
    tmp_path: Path, monkeypatch
):
    """A configured broken alias must fail closed without an internal traceback."""
    roots = RootsSettings(default_root=tmp_path / "alias", extra_roots=())
    original = Path.resolve

    def refusing_root(path, *args, **kwargs):
        if path == roots.default_root:
            raise PermissionError("isolated permission-denied fixture")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", refusing_root)
    with pytest.raises(CodedToolError) as exc:
        resolve_path("new.txt", roots=roots)
    assert exc.value.telemetry_code == "path_resolve_failed"


def test_case_sensitive_file_names_are_not_silently_conflated(tmp_path: Path):
    root = tmp_path / "case"
    root.mkdir()
    (root / "Case.txt").write_text("upper")
    (root / "case.txt").write_text("lower")
    roots = RootsSettings(default_root=root, extra_roots=())
    assert resolve_path("Case.txt", roots=roots).read_text() == "upper"
    assert resolve_path("case.txt", roots=roots).read_text() == "lower"
