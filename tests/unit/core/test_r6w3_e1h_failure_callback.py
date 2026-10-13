"""R6W3-01/03/04/05: failure-to-record must never mask the original exit.

These in-process tests supplement real-entry subprocess fault cases.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

from binnacle import startup_imports
from binnacle.manager_bootstrap import (
    capture_startup_root,
    record_early_failure,
)


def test_record_callback_system_exit_never_replaces_original_failure(
    monkeypatch, caplog
):
    original = startup_imports.StartupImportFailed(
        "binnacle.provenance", "SyntaxError", "provenance.py:2"
    )

    def fail_required(name):
        raise original

    def fail_record(_failure):
        raise SystemExit("SENSITIVE_SECONDARY_EXIT")

    monkeypatch.setattr(
        startup_imports,
        "runtime_module_names",
        lambda _system=None: ("binnacle.provenance",),
    )
    monkeypatch.setattr(startup_imports, "_required_import", fail_required)
    with pytest.raises(startup_imports.StartupImportFailed) as found:
        startup_imports.import_runtime_modules(on_failure=fail_record)
    assert found.value is original
    assert found.value.code == startup_imports.EX_STARTUP_IMPORT
    assert "event=startup_import_record_error" in caplog.text
    assert "error_class=SystemExit" in caplog.text
    assert "SENSITIVE_SECONDARY_EXIT" not in caplog.text


def test_record_callback_uses_only_previous_validated_root(tmp_path, monkeypatch):
    failure = startup_imports.StartupImportFailed(
        "binnacle.provenance", "SyntaxError", "provenance.py:2"
    )
    config = sys.modules.get("binnacle.config")
    assert config is not None

    def never_reinitialize():
        raise SystemExit("SENSITIVE_SETTINGS_RELOAD")

    monkeypatch.setattr(config, "get_settings", never_reinitialize)
    assert record_early_failure("mcp-server", failure, tmp_path)
    receipt = tmp_path / "startup-import" / "mcp-server.json"
    value = json.loads(receipt.read_text(encoding="utf-8"))
    assert value["module"] == "binnacle.provenance"
    assert value["error_class"] == "SyntaxError"


def test_no_validated_root_cannot_create_receipt_elsewhere(tmp_path, caplog):
    failure = startup_imports.StartupImportFailed(
        "binnacle.config", "SystemExit", "config.py:490"
    )
    assert record_early_failure("job-manager", failure, None) is False
    assert "reason=no_trusted_root" in caplog.text
    assert list(tmp_path.iterdir()) == []


def test_darwin_uses_file_only_root_and_rejects_env_override(monkeypatch, tmp_path):
    config = tmp_path / "config.toml"
    jobs = tmp_path / "accepted" / "jobs"
    config.write_text(
        f'[jobs]\ndir = "{jobs}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("BINNACLE_CONFIG_FILE", str(config))
    # Restore a true file-only manager environment for the positive control:
    # CI/test harnesses may set independent BINNACLE_JOBS__ or runtime keys.
    for key in tuple(os.environ):
        if key.startswith(
            ("BINNACLE_JOBS__", "BINNACLE_RUN_COMMAND__", "BINNACLE_RUNTIME_DIR")
        ):
            monkeypatch.delenv(key, raising=False)
    if sys.platform == "darwin":
        assert (
            capture_startup_root(process="job-manager", system="Darwin") == jobs.parent
        )
    monkeypatch.setenv("BINNACLE_JOBS__DIR", str(tmp_path / "rejected" / "jobs"))
    assert capture_startup_root(process="job-manager", system="Darwin") is None
    assert not (tmp_path / "rejected").exists()
