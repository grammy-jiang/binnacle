"""Direct, branch-complete production CLI entry tests (R6W3 coverage hardening).

Real subprocess import-failure cases run separately in e1h_preentry_guard.
These tests exercise dispatch without starting any MCP or launchd service.
"""

from __future__ import annotations

import builtins
import logging
import sys
from types import ModuleType

import pytest

from binnacle import entrypoint, startup_imports
from binnacle import manager_bootstrap as bootstrap


def _cli_with_main(monkeypatch, main):
    module = ModuleType("binnacle.cli")
    module.main = main
    monkeypatch.setitem(sys.modules, "binnacle.cli", module)
    return module


def test_nonserve_dispatch_has_no_preflight_or_service_side_effect(monkeypatch):
    actions = []
    monkeypatch.setattr(sys, "argv", ["binnacle", "doctor"])
    _cli_with_main(monkeypatch, lambda: actions.append("doctor"))

    def should_not_run(*args, **kwargs):
        raise AssertionError("nonserve must not enter the serving startup gate")

    monkeypatch.setattr(startup_imports, "import_runtime_modules", should_not_run)
    entrypoint.main()
    assert actions == ["doctor"]


@pytest.mark.parametrize("command", ["serve", "doctor"])
def test_cli_main_failure_after_import_keeps_normal_dispatch_semantics(
    monkeypatch, command, tmp_path
):
    events = []
    monkeypatch.setattr(sys, "argv", ["binnacle", command])
    _cli_with_main(
        monkeypatch,
        lambda: events.append(command) or (_ for _ in ()).throw(SystemExit(75)),
    )
    monkeypatch.setattr(bootstrap, "capture_startup_root", lambda **kwargs: tmp_path)
    monkeypatch.setattr(startup_imports, "import_runtime_modules", lambda **kwargs: ())
    with pytest.raises(SystemExit) as found:
        entrypoint.main()
    assert found.value.code == 75
    assert events == [command]


def test_successful_serve_guards_before_cli_dispatch(monkeypatch, tmp_path):
    steps = []
    monkeypatch.setattr(sys, "argv", ["binnacle", "serve"])
    monkeypatch.setattr(
        bootstrap,
        "capture_startup_root",
        lambda **kwargs: steps.append(("capture", kwargs)) or tmp_path,
    )

    def checked(*, on_failure):
        assert callable(on_failure)
        assert startup_imports.serving_entry_marked()
        steps.append(("checked", None))
        return ()

    monkeypatch.setattr(startup_imports, "import_runtime_modules", checked)
    _cli_with_main(
        monkeypatch,
        lambda: steps.append(("cli", startup_imports.serving_entry_marked())),
    )
    assert not startup_imports.serving_entry_marked()
    entrypoint.main()
    assert [step for step, _ in steps] == ["capture", "checked", "cli"]
    assert steps[-1][1] is True
    assert steps[0][1] == {"process": "mcp-server", "system": ""}
    assert not startup_imports.serving_entry_marked()


def test_required_import_failure_calls_record_callback_before_aborting(
    monkeypatch, tmp_path
):
    steps = []
    monkeypatch.setattr(sys, "argv", ["binnacle", "serve"])
    monkeypatch.setattr(bootstrap, "capture_startup_root", lambda **kwargs: tmp_path)
    failure = startup_imports.StartupImportFailed(
        "binnacle.features.files.files_server", "SyntaxError", "binnacle/files.py:5"
    )

    def required(*, on_failure):
        steps.append(("required", startup_imports.serving_entry_marked()))
        on_failure(failure)
        raise failure

    monkeypatch.setattr(startup_imports, "import_runtime_modules", required)
    monkeypatch.setattr(
        bootstrap,
        "record_early_failure",
        lambda process, fault, root: steps.append((process, fault, root)) or True,
    )
    _cli_with_main(monkeypatch, lambda: steps.append(("unreachable", None)))
    with pytest.raises(startup_imports.StartupImportFailed) as found:
        entrypoint.main()
    assert found.value is failure
    assert found.value.code == 70
    assert steps == [("required", True), ("mcp-server", failure, tmp_path)]
    assert not startup_imports.serving_entry_marked()


@pytest.mark.parametrize(
    ("problem", "expected"),
    [
        (SystemExit("SECRET_IMPORT_SYSTEM_EXIT"), "SystemExit"),
        (SyntaxError("SECRET_IMPORT_SYNTAX"), "SyntaxError"),
        (RuntimeError("SECRET_IMPORT_RUNTIME"), "RuntimeError"),
    ],
)
def test_cli_import_error_is_redacted_and_exits_70(
    monkeypatch, caplog, tmp_path, problem, expected
):
    monkeypatch.setattr(sys, "argv", ["binnacle", "serve"])
    monkeypatch.setattr(bootstrap, "capture_startup_root", lambda **kwargs: tmp_path)
    monkeypatch.setattr(startup_imports, "import_runtime_modules", lambda **kwargs: ())
    monkeypatch.setattr(
        startup_imports, "_raising_frame", lambda error, module: "binnacle/cli.py:12"
    )
    recorded = []
    monkeypatch.setattr(
        bootstrap,
        "record_early_failure",
        lambda process, failure, root: (
            recorded.append((process, failure, root)) or True
        ),
    )
    original = builtins.__import__

    def broken(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "binnacle.cli":
            raise problem
        return original(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", broken)
    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(startup_imports.StartupImportFailed) as found,
    ):
        entrypoint.main()
    assert found.value.code == 70
    assert found.value.error_class == expected
    assert found.value.where == "binnacle/cli.py:12"
    assert len(recorded) == 1
    assert recorded[0][0] == "mcp-server"
    assert recorded[0][1] is found.value
    assert recorded[0][2] == tmp_path
    assert "event=startup_import_failed" in caplog.text
    assert "SECRET_IMPORT" not in caplog.text
    assert not startup_imports.serving_entry_marked()


@pytest.mark.parametrize(
    "problem",
    [
        KeyboardInterrupt(),
        startup_imports.StartupImportFailed("binnacle.cli", "SyntaxError", "cli.py:3"),
    ],
)
def test_cli_import_keyboard_or_previous_import_failure_is_not_rewrapped(
    monkeypatch, problem, tmp_path
):
    monkeypatch.setattr(sys, "argv", ["binnacle", "serve"])
    monkeypatch.setattr(bootstrap, "capture_startup_root", lambda **kwargs: tmp_path)
    monkeypatch.setattr(startup_imports, "import_runtime_modules", lambda **kwargs: ())
    original = builtins.__import__

    def broken(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "binnacle.cli":
            raise problem
        return original(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", broken)
    with pytest.raises(type(problem)) as found:
        entrypoint.main()
    assert found.value is problem
    assert not startup_imports.serving_entry_marked()


def test_capture_failure_prevents_serve_preflight_and_cli(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["binnacle", "serve"])
    fail = startup_imports.StartupImportFailed(
        "binnacle.config", "ImportError", "config.py:1"
    )

    def missing_root(**_kwargs):
        raise fail

    monkeypatch.setattr(bootstrap, "capture_startup_root", missing_root)
    monkeypatch.setattr(
        startup_imports,
        "import_runtime_modules",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("entered")),
    )
    with pytest.raises(startup_imports.StartupImportFailed) as found:
        entrypoint.main()
    assert found.value is fail
    assert not startup_imports.serving_entry_marked()
