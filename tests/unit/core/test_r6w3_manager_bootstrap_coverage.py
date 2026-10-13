"""Fail-closed start-up snapshot and manager entry branches, without real jobs.

The durable acceptance requires actual -m/console and IPC tests separately.
This suite locks the pure bootstrap decisions and their failure boundaries.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle import job_manager_cli, startup_imports
from binnacle import manager_bootstrap as boot
from binnacle.platform.darwin import job_manager_start


def _settings(root: Path):
    return SimpleNamespace(jobs=SimpleNamespace(dir=root / "jobs"))


@pytest.mark.parametrize(
    ("process", "system", "module_name", "method"),
    [
        ("mcp-server", "", "binnacle.config", "get_settings"),
        ("job-manager", "Linux", "binnacle.config", "get_settings"),
        (
            "job-manager",
            "Darwin",
            "binnacle.platform.darwin.job_manager_config",
            "read_config",
        ),
    ],
)
def test_capture_returns_only_one_approved_root_snapshot(
    monkeypatch, tmp_path, process, system, module_name, method
):
    called = []
    module = SimpleNamespace()

    def actual():
        called.append(method)
        return _settings(tmp_path / "authorized")

    module.get_settings = lambda: (_ for _ in ()).throw(
        AssertionError("wrong frontend source")
    )
    module.read_config = lambda: (_ for _ in ()).throw(
        AssertionError("wrong manager source")
    )
    setattr(module, method, actual)

    def required(name):
        called.append(name)
        assert name == module_name
        return module

    monkeypatch.setattr(boot, "_required_import", required)
    root = boot.capture_startup_root(process=process, system=system)
    assert root == tmp_path / "authorized"
    assert called == [module_name, method]


@pytest.mark.parametrize("error_type", [ValueError, OSError])
def test_capture_invalid_config_has_no_guessed_fallback(monkeypatch, error_type):
    def failed(_name):
        raise error_type("secret invalid config")

    monkeypatch.setattr(boot, "_required_import", failed)
    assert boot.capture_startup_root(process="job-manager", system="Darwin") is None


@pytest.mark.parametrize("error_type", [SystemExit, RuntimeError, SyntaxError])
def test_capture_unexpected_source_failure_aborts_redacted(
    monkeypatch, caplog, error_type
):
    def failed(_name):
        raise error_type("SENSITIVE_USER_CONFIG")

    monkeypatch.setattr(boot, "_required_import", failed)
    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(startup_imports.StartupImportFailed) as result,
    ):
        boot.capture_startup_root(process="mcp-server", system="Linux")
    assert result.value.code == 70
    assert result.value.error_class == error_type.__name__
    assert result.value.module == "binnacle.config"
    assert "event=startup_import_failed" in caplog.text
    assert "SENSITIVE_USER_CONFIG" not in caplog.text


def test_capture_required_import_failure_keeps_original_identity(monkeypatch, caplog):
    original = startup_imports.StartupImportFailed(
        "binnacle.config", "SyntaxError", "config.py:2"
    )

    def failed(_name):
        raise original

    monkeypatch.setattr(boot, "_required_import", failed)
    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(startup_imports.StartupImportFailed) as result,
    ):
        boot.capture_startup_root(process="job-manager", system="Linux")
    assert result.value is original
    assert "event=startup_import_failed" in caplog.text


def test_capture_keyboard_interrupt_is_not_hidden(monkeypatch):
    def interrupted(_name):
        raise KeyboardInterrupt

    monkeypatch.setattr(boot, "_required_import", interrupted)
    with pytest.raises(KeyboardInterrupt):
        boot.capture_startup_root(process="job-manager", system="Darwin")


def test_receipt_without_root_is_fail_closed_and_describes_reason(caplog):
    failure = startup_imports.StartupImportFailed(
        "binnacle.config", "SyntaxError", "x.py:3"
    )
    with caplog.at_level(logging.ERROR):
        assert boot.record_early_failure("mcp-server", failure, None) is False
    assert "event=startup_import_record_error" in caplog.text
    assert "reason=no_trusted_root" in caplog.text


@pytest.mark.parametrize("saved", [True, False])
def test_receipt_writer_only_uses_previous_root(monkeypatch, tmp_path, saved):
    observed = []
    failure = startup_imports.StartupImportFailed(
        "binnacle.config", "SyntaxError", "x.py:3"
    )

    def save(process, fault, root):
        observed.append((process, fault, root))
        return saved

    monkeypatch.setattr(boot, "record_start_failure", save)
    assert boot.record_early_failure("job-manager", failure, tmp_path) is saved
    assert observed == [("job-manager", failure, tmp_path)]


@pytest.mark.parametrize("failure_type", [SystemExit, OSError, RuntimeError])
def test_record_secondary_exception_cannot_replace_root_failure(
    monkeypatch, caplog, tmp_path, failure_type
):
    original = startup_imports.StartupImportFailed(
        "binnacle.provenance", "SyntaxError", "provenance.py:2"
    )

    def fails(*_args):
        raise failure_type("SENSITIVE_SECONDARY_RECORD_FAILURE")

    monkeypatch.setattr(boot, "record_start_failure", fails)
    with caplog.at_level(logging.ERROR):
        assert boot.record_early_failure("job-manager", original, tmp_path) is False
    assert "event=startup_import_record_error" in caplog.text
    assert f"error_class={failure_type.__name__}" in caplog.text
    assert "SENSITIVE_SECONDARY_RECORD_FAILURE" not in caplog.text
    assert original.code == 70


def test_record_keyboard_interrupt_is_not_suppressed(monkeypatch, tmp_path):
    def interrupt(*_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(boot, "record_start_failure", interrupt)
    fault = startup_imports.StartupImportFailed(
        "binnacle.provenance", "SyntaxError", "x.py:3"
    )
    with pytest.raises(KeyboardInterrupt):
        boot.record_early_failure("job-manager", fault, tmp_path)


@pytest.mark.parametrize("system", ["Linux", "Darwin"])
def test_bootstrap_eager_set_after_root_capture_with_right_format(
    monkeypatch, tmp_path, system
):
    calls = []
    failure = startup_imports.StartupImportFailed(
        "binnacle.config", "SyntaxError", "binnacle/config.py:1"
    )

    def capture(**kwargs):
        calls.append(("capture", kwargs))
        return tmp_path

    def check(**kwargs):
        calls.append(("import", kwargs))
        kwargs["on_failure"](failure)
        return ()

    def record(process, fault, path):
        calls.append(("record", (process, fault, path)))
        return True

    monkeypatch.setattr(boot, "capture_startup_root", capture)
    monkeypatch.setattr(boot, "import_manager_modules", check)
    monkeypatch.setattr(boot, "record_early_failure", record)
    boot.bootstrap_manager_entry(system)
    assert [kind for kind, _ in calls] == ["capture", "import", "record"]
    assert calls[0][1] == {"process": "job-manager", "system": system}
    assert calls[1][1]["system"] == system
    assert calls[1][1]["process"] == "job-manager"
    assert calls[1][1]["log_format"] == (
        "%(asctime)s.%(msecs)03d %(levelname)s: %(message)s"
    )
    assert calls[-1][1] == ("job-manager", failure, tmp_path)


def test_bootstrap_configuration_fault_stops_before_manager_import(monkeypatch):
    fault = startup_imports.StartupImportFailed(
        "binnacle.config", "SyntaxError", "c.py:1"
    )

    def fail(**_kwargs):
        raise fault

    monkeypatch.setattr(boot, "capture_startup_root", fail)
    monkeypatch.setattr(
        boot,
        "import_manager_modules",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not import")),
    )
    with pytest.raises(startup_imports.StartupImportFailed) as result:
        boot.bootstrap_manager_entry("Linux")
    assert result.value is fault


def test_console_backend_only_begins_after_manager_bootstrap(monkeypatch):
    from binnacle.features.commands import job_manager

    order = []
    monkeypatch.setattr(
        boot,
        "bootstrap_manager_entry",
        lambda system: order.append(("bootstrap", system)),
    )
    monkeypatch.setattr(job_manager, "main", lambda: order.append(("manager", None)))
    job_manager_cli.main()
    assert order == [("bootstrap", "Linux"), ("manager", None)]


def test_console_backend_cannot_start_after_failed_bootstrap(monkeypatch):
    from binnacle.features.commands import job_manager

    original = startup_imports.StartupImportFailed(
        "binnacle.config", "SyntaxError", "c.py:1"
    )
    monkeypatch.setattr(
        boot,
        "bootstrap_manager_entry",
        lambda _system: (_ for _ in ()).throw(original),
    )
    monkeypatch.setattr(
        job_manager,
        "main",
        lambda: (_ for _ in ()).throw(AssertionError("manager ran")),
    )
    with pytest.raises(startup_imports.StartupImportFailed) as result:
        job_manager_cli.main()
    assert result.value is original


@pytest.mark.parametrize("args", [None, [], ["--help"]])
def test_darwin_manager_trampoline_preserves_arguments_and_exit(monkeypatch, args):
    from binnacle.platform.darwin import job_manager_entry

    seen = []
    monkeypatch.setattr(
        job_manager_entry,
        "main",
        lambda received: seen.append(received) or 75,
    )
    assert job_manager_start.main(args) == 75
    assert seen == [args]
