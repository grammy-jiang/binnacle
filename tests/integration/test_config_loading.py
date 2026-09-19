"""Deployment-level configuration loading and precedence scenarios."""

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from binnacle import config
from binnacle.watchdog_config import WatchdogRootSettings


def clear_binnacle_env(monkeypatch) -> None:
    for key in tuple(os.environ):
        if key.startswith("BINNACLE_"):
            monkeypatch.delenv(key, raising=False)


def test_defaults_load_without_config_file(tmp_path, monkeypatch):
    clear_binnacle_env(monkeypatch)
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(tmp_path / "missing.toml"))

    settings = config.Settings()

    assert settings.serve.host == "127.0.0.1"
    assert settings.serve.port == 8000
    assert settings.roots.extra_roots == (Path("/tmp"),)
    assert settings.jobs.keep_newest == 50
    assert settings.client_tools["openai-mcp"] == (
        "read_file",
        "list_files",
        "search_text",
        "run_command",
        "job_status",
        "stop_job",
    )


def test_toml_loads_nested_deployment_settings(tmp_path, monkeypatch):
    clear_binnacle_env(monkeypatch)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[serve]
host = "0.0.0.0"
port = 9123

[roots]
default_root = "/tmp/project-root"
extra_roots = ["/tmp", "/var/tmp"]

[jobs]
keep_newest = 7
listing_history_limit = 3

[indexed_context]
enabled = true
max_open_indexes = 4

[search_text]
timeout_s = 31
result_max_bytes = 70000
"""
    )
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(cfg))

    settings = config.Settings()

    assert settings.serve.host == "0.0.0.0"
    assert settings.serve.port == 9123
    assert settings.roots.default_root == Path("/tmp/project-root")
    assert settings.roots.extra_roots == (Path("/tmp"), Path("/var/tmp"))
    assert settings.jobs.keep_newest == 7
    assert settings.jobs.listing_history_limit == 3
    assert settings.indexed_context.enabled is True
    assert settings.indexed_context.max_open_indexes == 4
    assert settings.search_text.timeout_s == 31
    assert settings.search_text.result_max_bytes == 70000


def test_environment_overrides_toml(tmp_path, monkeypatch):
    clear_binnacle_env(monkeypatch)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[serve]
port = 8123

[jobs]
keep_newest = 8

[indexed_context]
enabled = false
"""
    )
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(cfg))
    monkeypatch.setenv("BINNACLE_SERVE__PORT", "9456")
    monkeypatch.setenv("BINNACLE_JOBS__KEEP_NEWEST", "11")
    monkeypatch.setenv("BINNACLE_INDEXED_CONTEXT__ENABLED", "true")

    settings = config.Settings()

    assert settings.serve.port == 9456
    assert settings.jobs.keep_newest == 11
    assert settings.indexed_context.enabled is True


def test_invalid_toml_is_a_configuration_failure(tmp_path, monkeypatch):
    clear_binnacle_env(monkeypatch)
    cfg = tmp_path / "bad.toml"
    cfg.write_text("[serve\nport = 8000\n")
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(cfg))

    with pytest.raises(ValueError) as exc:
        config.Settings()
    assert type(exc.value).__name__ == "TOMLDecodeError"


def test_invalid_constrained_value_fails_startup_configuration(tmp_path, monkeypatch):
    clear_binnacle_env(monkeypatch)
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(tmp_path / "missing.toml"))
    monkeypatch.setenv("BINNACLE_JOBS__KEEP_NEWEST", "0")

    with pytest.raises(ValidationError):
        config.Settings()


def test_get_settings_cache_requires_explicit_clear_for_runtime_env_change(
    tmp_path, monkeypatch
):
    clear_binnacle_env(monkeypatch)
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(tmp_path / "missing.toml"))
    config.get_settings.cache_clear()
    monkeypatch.setenv("BINNACLE_SERVE__PORT", "8100")
    first = config.get_settings()

    monkeypatch.setenv("BINNACLE_SERVE__PORT", "8200")
    assert config.get_settings() is first
    assert config.get_settings().serve.port == 8100

    config.get_settings.cache_clear()
    assert config.get_settings().serve.port == 8200
    config.get_settings.cache_clear()


def test_watchdog_section_is_ignored_by_core_but_loaded_by_companion(
    tmp_path, monkeypatch
):
    clear_binnacle_env(monkeypatch)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[serve]
port = 8123

[watchdog]
interval_s = 7
upstream_host = "example.test"
"""
    )
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(cfg))

    core = config.Settings()
    companion = WatchdogRootSettings()

    assert core.serve.port == 8123
    assert not hasattr(core, "watchdog")
    assert companion.watchdog.interval_s == 7
    assert companion.watchdog.upstream_host == "example.test"


def test_core_unknown_sections_do_not_break_forward_compatible_config(
    tmp_path, monkeypatch
):
    clear_binnacle_env(monkeypatch)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[serve]
port = 8333

[future_feature]
enabled = true
mode = "experimental"
"""
    )
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(cfg))

    assert config.Settings().serve.port == 8333
