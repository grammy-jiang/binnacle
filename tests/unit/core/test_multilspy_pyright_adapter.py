"""Pyright multilspy adapter: fail-closed pure policy without optional package."""

import pytest

from binnacle.features.development_intelligence.multilspy_pyright import (
    PyrightOptions,
    _authorized_file,
    create_pyright_adapter,
    normalize_locations,
)

POSITION = {"line": 0, "character": 4}
SPAN = {"start": POSITION, "end": {"line": 0, "character": 9}}


@pytest.mark.parametrize(
    ("mode", "diagnostics"),
    [
        ("off", "openFilesOnly"),
        ("basic", "openFilesOnly"),
        ("standard", "workspace"),
        ("strict", "workspace"),
    ],
)
def test_allowed_pyright_options(mode, diagnostics):
    value = PyrightOptions(type_checking_mode=mode, diagnostic_mode=diagnostics)
    assert value.type_checking_mode == mode
    assert value.diagnostic_mode == diagnostics


@pytest.mark.parametrize("bad", ["any", "mypy", "", None])
def test_unknown_type_check_mode_rejected(bad):
    with pytest.raises(ValueError, match="invalid_pyright_type_checking_mode"):
        PyrightOptions(type_checking_mode=bad)


@pytest.mark.parametrize("bad", ["open-files-only", "all", "none", None])
def test_unknown_diagnostic_mode_rejected(bad):
    with pytest.raises(ValueError, match="invalid_pyright_diagnostic_mode"):
        PyrightOptions(diagnostic_mode=bad)


@pytest.mark.parametrize("bad", [-1, 0, 121, float("nan")])
def test_initialize_timeout_bounded(bad):
    with pytest.raises(ValueError, match="invalid_pyright_initialize_deadline"):
        PyrightOptions(initialize_timeout_s=bad)


def test_valid_local_document_location_and_location_link(tmp_path):
    file = tmp_path / "example.py"
    file.write_text("def greet(): return 1\n")
    location = {"uri": file.as_uri(), "range": SPAN}
    link = {
        "targetUri": file.as_uri(),
        "targetRange": SPAN,
        "targetSelectionRange": SPAN,
        # LSP originSelectionRange intentionally omitted (optional).
    }
    for original in (location, link):
        (result,) = normalize_locations(tmp_path, [original])
        assert result["relativePath"] == "example.py"
        assert result["range"] == SPAN
        assert result["absolutePath"] == str(file)
    assert len(normalize_locations(tmp_path, [location, link])) == 2
    assert normalize_locations(tmp_path, None) == []
    assert normalize_locations(tmp_path, []) == []


def test_single_location_object_is_supported(tmp_path):
    file = tmp_path / "main.py"
    file.write_text("variable = 1\n")
    (result,) = normalize_locations(tmp_path, {"uri": file.as_uri(), "range": SPAN})
    assert result["relativePath"] == "main.py"


@pytest.mark.parametrize(
    "bad_uri",
    [
        "https://example.com/secret.py",
        "file://attacker.example/secret.py",
        "data:text/html,hello",
        "file:///tmp/secret.py?token=abc",
    ],
)
def test_nonlocal_or_unapproved_location_uris_refused(tmp_path, bad_uri):
    with pytest.raises(ValueError):
        normalize_locations(
            tmp_path,
            [
                {
                    "targetUri": bad_uri,
                    "targetSelectionRange": SPAN,
                }
            ],
        )


def test_explicit_external_workspace_location_fails_closed(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "private.py"
    outside.write_text("secret = True\n")
    with pytest.raises(ValueError, match="pyright_result_outside_workspace"):
        normalize_locations(
            root,
            [
                {
                    "targetUri": outside.as_uri(),
                    "targetSelectionRange": SPAN,
                }
            ],
        )


def test_result_symlink_to_external_workspace_file_fails_closed(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "external.py"
    outside.write_text("secret = True\n")
    (root / "linked.py").symlink_to(outside)
    with pytest.raises(ValueError, match="pyright_result_outside_workspace"):
        normalize_locations(
            root,
            [
                {
                    "uri": (root / "linked.py").as_uri(),
                    "range": SPAN,
                }
            ],
        )


@pytest.mark.parametrize(
    "invalid",
    [
        7,
        None,
        "string",
        [1],
        [{"uri": 5, "range": SPAN}],
        [{"targetUri": "file:///x"}],
    ],
)
def test_invalid_result_shapes_fail_closed(tmp_path, invalid):
    if invalid is None:
        assert normalize_locations(tmp_path, invalid) == []
    else:
        with pytest.raises((TypeError, ValueError)):
            normalize_locations(tmp_path, invalid)


def test_result_count_bounded(tmp_path):
    with pytest.raises(ValueError, match="pyright_location_limit"):
        normalize_locations(tmp_path, [{}] * 2049)


def test_only_explicit_in_root_source_files_can_be_opened(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    file = root / "module.py"
    file.write_text("answer = 42\n")
    relative, absolute = _authorized_file(root, "module.py")
    assert relative == "module.py"
    assert absolute == file
    with pytest.raises(ValueError, match="pyright_source_outside_workspace"):
        _authorized_file(root, "../private.py")
    with pytest.raises(ValueError, match="pyright_source_outside_workspace"):
        _authorized_file(root, str(file))
    with pytest.raises((ValueError, FileNotFoundError)):
        _authorized_file(root, "nonexistent.py")


def test_symlink_escape_is_not_read(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "secret.py"
    outside.write_text("secret = 'not accessible'\n")
    (root / "linked.py").symlink_to(outside)
    with pytest.raises(ValueError, match="pyright_source_outside_workspace"):
        _authorized_file(root, "linked.py")


class FakeProfile:
    trace_lsp_communication = False


def test_missing_or_relative_binary_fails_before_importing_multilspy(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    for candidate in ("pyright-langserver", "/unknown/pyright-langserver"):
        with pytest.raises(ValueError, match="pyright_executable"):
            create_pyright_adapter(FakeProfile(), None, root, executable=candidate)


def test_full_raw_wire_logging_is_prohibited(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    binary = tmp_path / "binary"
    binary.write_text("no execution needed")
    profile = FakeProfile()
    profile.trace_lsp_communication = True
    with pytest.raises(ValueError, match="raw_wire_logging"):
        create_pyright_adapter(profile, None, root, executable=binary)


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"start": {"line": 0, "character": -1}, "end": POSITION},
        {"start": {"line": True, "character": 0}, "end": POSITION},
        {"start": {"line": 0, "character": 0}, "end": {"line": 0}},
    ],
)
def test_malformed_location_ranges_are_rejected(tmp_path, bad):
    file = tmp_path / "example.py"
    file.write_text("def greet(): return 1\n")
    with pytest.raises(ValueError, match="invalid_pyright_location_range"):
        normalize_locations(tmp_path, [{"uri": file.as_uri(), "range": bad}])
