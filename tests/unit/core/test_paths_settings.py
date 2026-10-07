"""Explicit roots apply to resolution and hints, including error paths."""

from types import SimpleNamespace

import pytest

from binnacle.config import RootsSettings
from binnacle.errors import CodedToolError
from binnacle.features.files import paths


def no_global_settings():
    raise AssertionError("explicit path policy must not read global settings")


def test_explicit_roots_select_relative_base_and_allowed_paths(tmp_path, monkeypatch):
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    first = RootsSettings(default_root=left, extra_roots=())
    second = RootsSettings(default_root=right, extra_roots=())
    monkeypatch.setattr(paths, "get_settings", no_global_settings)
    assert paths.resolve_path(" @file\0 ", roots=first) == left / "file"
    assert paths.resolve_path("file", roots=second) == right / "file"
    assert paths.resolve_path(str(left / "file"), roots=first) == left / "file"
    with pytest.raises(CodedToolError, match="outside allowed roots"):
        paths.resolve_path(str(right / "file"), roots=first)
    (left / "escape").symlink_to(right)
    with pytest.raises(CodedToolError, match="outside allowed roots"):
        paths.resolve_path("escape/file", roots=first)


def test_explicit_hint_does_not_enumerate_parent_outside_custom_roots(
    tmp_path, monkeypatch
):
    roots = RootsSettings(default_root=tmp_path / "nonexistent", extra_roots=())
    (tmp_path / "private-sibling").write_text("private")
    monkeypatch.setattr(paths, "get_settings", no_global_settings)
    monkeypatch.setattr(
        type(tmp_path),
        "iterdir",
        lambda parent: pytest.fail("out-of-policy enumeration"),
    )
    assert paths.resolve_path(".", roots=roots) == roots.default_root
    assert paths.nearby_hint(tmp_path, roots=roots) == ""


def test_explicit_hint_preserves_empty_missing_and_sorted_limit(tmp_path, monkeypatch):
    roots = RootsSettings(default_root=tmp_path, extra_roots=())
    monkeypatch.setattr(paths, "get_settings", no_global_settings)
    assert (
        paths.nearby_hint(tmp_path, roots=roots) == f" Directory {tmp_path} is empty."
    )
    assert paths.nearby_hint(tmp_path / "missing", roots=roots) == ""
    (tmp_path / "adir").mkdir()
    for i in range(12):
        (tmp_path / f"b{i:02}").write_text("x")
    assert paths.nearby_hint(tmp_path, roots=roots) == (
        f" Files in {tmp_path}: adir/, "
        + ", ".join(f"b{i:02}" for i in range(9))
        + " …. Use list_files for more."
    )


def test_compatible_fallback_is_lazy_for_both_helpers(tmp_path, monkeypatch):
    for name in ("one", "two"):
        root = tmp_path / name
        root.mkdir()
        monkeypatch.setattr(
            paths,
            "get_settings",
            lambda root=root: SimpleNamespace(
                roots=RootsSettings(default_root=root, extra_roots=())
            ),
        )
        assert paths.resolve_path("relative") == root / "relative"
        assert paths.nearby_hint(root) == f" Directory {root} is empty."


def test_explicit_resolution_errors_keep_coded_contract(tmp_path, monkeypatch):
    roots = RootsSettings(default_root=tmp_path, extra_roots=())
    monkeypatch.setattr(paths, "get_settings", no_global_settings)

    def fail(path):
        raise OSError("cannot resolve")

    monkeypatch.setattr(type(tmp_path), "resolve", fail)
    with pytest.raises(CodedToolError) as exc:
        paths.resolve_path("file", roots=roots)
    assert exc.value.telemetry_code == "path_resolve_failed"
