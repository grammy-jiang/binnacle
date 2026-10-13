"""Boundary cases for the frozen E1 startup import and receipt functions.

All targets and mutation hooks are private test-owned values; the shared
provenance module is never re-imported as a side effect of recording failure.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle import startup_imports as startup


@pytest.mark.parametrize(
    "error",
    [
        KeyboardInterrupt(),
        startup.StartupImportFailed("binnacle.test", "SyntaxError", "x.py:1"),
    ],
)
def test_required_import_propagates_explicit_abort_without_wrapping(monkeypatch, error):
    def failed(_name):
        raise error

    monkeypatch.setattr(startup.importlib, "import_module", failed)
    with pytest.raises(type(error)) as found:
        startup._required_import("binnacle.test")
    assert found.value is error


@pytest.mark.parametrize(
    ("get_result", "expected"),
    [
        ("known", "abcd1234abcd"),
        ("blank", "unknown"),
        ("malformed", "unknown"),
        ("runtime", "unknown"),
    ],
)
def test_provenance_record_uses_only_a_previously_loaded_valid_module(
    monkeypatch, get_result, expected
):
    def get():
        if get_result == "runtime":
            raise RuntimeError("secret provenance was unavailable")
        if get_result == "blank":
            return SimpleNamespace(revision="")
        if get_result == "malformed":
            return SimpleNamespace(revision=None)
        return SimpleNamespace(revision="abcd1234abcd")

    monkeypatch.setitem(
        sys.modules, "binnacle.provenance", SimpleNamespace(runtime_provenance=get)
    )
    assert startup._loaded_source_revision() == expected


def test_provenance_revision_without_loaded_module_is_unknown(monkeypatch):
    monkeypatch.setitem(sys.modules, "binnacle.provenance", None)
    assert startup._loaded_source_revision() == "unknown"


def test_provenance_revision_keyboard_interrupt_is_not_swallowed(monkeypatch):
    def fail():
        raise KeyboardInterrupt

    monkeypatch.setitem(
        sys.modules, "binnacle.provenance", SimpleNamespace(runtime_provenance=fail)
    )
    with pytest.raises(KeyboardInterrupt):
        startup._loaded_source_revision()


def test_record_failure_preserves_original_exit_if_disk_replace_fails(
    monkeypatch, tmp_path, caplog
):
    failure = startup.StartupImportFailed(
        "binnacle.provenance", "SyntaxError", "p.py:3"
    )

    def no_replace(_from, _to):
        raise PermissionError("sensitive fixture error")

    monkeypatch.setattr(startup.os, "replace", no_replace)
    with caplog.at_level(logging.ERROR, logger="binnacle.startup_imports"):
        assert startup.record_start_failure("job-manager", failure, tmp_path) is False
    assert "event=startup_import_record_error process=job-manager" in caplog.text
    assert "sensitive fixture error" not in caplog.text


def test_record_clear_handles_unlink_permission_denial_without_leak(
    monkeypatch, tmp_path, caplog
):
    failure = startup.StartupImportFailed(
        "binnacle.provenance", "SyntaxError", "p.py:3"
    )
    assert startup.record_start_failure("mcp-server", failure, tmp_path)
    receipt = startup.record_path(tmp_path, "mcp-server")
    original = Path.unlink

    def deny_only_test_receipt(path, *args, **kwargs):
        if path == receipt:
            raise PermissionError("sensitive unlink failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", deny_only_test_receipt)
    with caplog.at_level(logging.WARNING, logger="binnacle.startup_imports"):
        startup.clear_record("mcp-server", tmp_path)
    assert receipt.exists()
    assert "event=startup_import_record_error process=mcp-server" in caplog.text
    assert "sensitive unlink failure" not in caplog.text


def test_optional_import_guard_does_not_load_optional_module(monkeypatch):
    seen = []
    monkeypatch.setattr(startup, "OPTIONAL_MODULES", ("binnacle.optional_test",))
    monkeypatch.setattr(
        startup,
        "runtime_module_names",
        lambda _system=None: ("binnacle.optional_test", "binnacle.required_test"),
    )
    monkeypatch.setattr(startup, "_required_import", lambda name: seen.append(name))
    assert startup.import_runtime_modules() == ()
    assert seen == ["binnacle.required_test"]


def test_early_failure_receipt_keyboard_interrupt_is_not_concealed(monkeypatch):
    problem = startup.StartupImportFailed(
        "binnacle.provenance", "SyntaxError", "provenance.py:2"
    )

    def needed(_name):
        raise problem

    def callback(_failure):
        raise KeyboardInterrupt

    monkeypatch.setattr(startup, "_required_import", needed)
    monkeypatch.setattr(
        startup, "manager_module_names", lambda _system=None: ("binnacle.provenance",)
    )
    with pytest.raises(KeyboardInterrupt):
        startup.import_manager_modules(on_failure=callback)


def test_diagnostics_ignore_frozen_bootstrap_and_importlib_frames(monkeypatch):
    root = Path(startup.__file__).resolve().parent

    def frame(filename, lineno):
        return SimpleNamespace(filename=filename, lineno=lineno)

    monkeypatch.setattr(
        startup.traceback,
        "extract_tb",
        lambda _tb: [
            frame(str(root / "synthetic_entry.py"), 41),
            frame("/usr/lib/python3.13/importlib/_bootstrap.py", 13),
            frame("<frozen importlib._bootstrap>", 11),
        ],
    )
    assert startup._raising_frame(
        RuntimeError("sensitive"), "binnacle.synthetic_entry"
    ) == ("binnacle/synthetic_entry.py:41")
