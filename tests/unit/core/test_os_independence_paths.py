"""OS5 canonical alias regressions; escapes remain denied."""

import sys
from pathlib import Path

import pytest

from binnacle.config import RootsSettings
from binnacle.errors import CodedToolError
from binnacle.features.files.error_text import caller_form
from binnacle.features.files.paths import nearby_hint, resolve_path

LINUX_ONLY = pytest.mark.skipif(
    sys.platform != "linux",
    reason="case-sensitive file names; default APFS volumes are case-insensitive (no Darwin counterpart: UNAVAILABLE on Darwin by release scope)",
)


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


@LINUX_ONLY
def test_case_sensitive_file_names_are_not_silently_conflated(tmp_path: Path):
    root = tmp_path / "case"
    root.mkdir()
    (root / "Case.txt").write_text("upper")
    (root / "case.txt").write_text("lower")
    roots = RootsSettings(default_root=root, extra_roots=())
    assert resolve_path("Case.txt", roots=roots).read_text() == "upper"
    assert resolve_path("case.txt", roots=roots).read_text() == "lower"


def _aliased_layout(tmp_path: Path) -> tuple[Path, Path, RootsSettings]:
    """A /tmp -> /private/tmp style alias over a root and a sibling outside it."""
    real = tmp_path / "private-tmp"
    (real / "root").mkdir(parents=True)
    (real / "outside").mkdir()
    (real / "outside" / "secret").write_text("secret")
    alias = tmp_path / "tmp"
    alias.symlink_to(real, target_is_directory=True)
    (real / "root" / "escape").symlink_to(alias / "outside", target_is_directory=True)
    return alias, real, RootsSettings(default_root=alias / "root", extra_roots=())


@pytest.mark.parametrize(
    ("host", "spelled"), [("darwin", "tmp"), ("linux", "private-tmp")]
)
def test_outside_refusal_spells_path_as_caller_on_macos_only(
    tmp_path: Path, monkeypatch, host, spelled
):
    """r5 L3 (SD-50): wording follows the caller's spelling; the decision does not."""
    from binnacle.platform import composition

    monkeypatch.setattr(composition, "host_os_family", lambda: host)
    alias, real, roots = _aliased_layout(tmp_path)
    shown = tmp_path / spelled / "outside" / "secret"
    for request in ("escape/secret", str(alias / "outside/secret")):
        with pytest.raises(CodedToolError) as exc:
            resolve_path(request, roots=roots)
        assert exc.value.telemetry_code == "path_outside_root"
        assert (
            str(exc.value) == f"Path outside allowed roots ({alias / 'root'}): {shown}"
        )
    # Inside the root the real path is still what callers receive.
    assert resolve_path("new.txt", roots=roots) == real / "root" / "new.txt"


def test_caller_form_follows_only_in_root_links_and_never_misnames(tmp_path: Path):
    alias, real, roots = _aliased_layout(tmp_path)
    canonical = roots.canonical_allowed

    def real_path(request: Path) -> Path:
        # Path.resolve() raises RuntimeError on a symlink loop before 3.13;
        # caught as caller_form catches it, the loop's own real location.
        try:
            return request.resolve()
        except (RuntimeError, OSError, ValueError):
            return request.parent.resolve() / request.name

    def shown(request: Path) -> Path:
        return caller_form(request, real_path(request), canonical)

    assert shown(alias / "root/escape/secret") == alias / "outside/secret"
    assert shown(alias / "outside/../outside/secret") == alias / "outside/secret"
    (real / "root" / "rel").symlink_to("../root/escape", target_is_directory=True)
    assert shown(alias / "root/rel/secret") == alias / "outside/secret"
    (real / "root" / "loop").symlink_to("loop")
    loop = alias / "root/loop"
    assert shown(loop) == real_path(loop) == real / "root/loop"  # falls back
    # A spelling that names another location falls back to the real path.
    resolved = (real / "outside" / "secret").resolve()
    assert caller_form(alias / "root/x", resolved, canonical) == resolved
    assert caller_form(Path("relative"), resolved, canonical) == resolved
