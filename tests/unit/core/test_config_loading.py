"""Deployment-level configuration loading and precedence scenarios."""

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from binnacle import config
from binnacle.companions.watchdog.watchdog_config import WatchdogRootSettings


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
    assert settings.jobs.owner == "auto"
    assert settings.jobs.warmup_s == 1.0
    assert settings.jobs.removed_keys == ()
    assert settings.run_command.auto_background_patterns == {}
    assert settings.telemetry.tokenizer.enabled is False
    assert settings.telemetry.tokenizer.encoding == "o200k_base"
    assert settings.telemetry.tokenizer.client_prefixes == ("openai-mcp",)
    assert settings.search_text.exact_execution == "streaming"
    assert settings.search_text.adaptive_discovery_enabled is False
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

[jobs.blocking_wall_budget_s_by_client]
"openai-mcp" = 120
"openai-mcp(ChatGPT)" = 90

[run_command.auto_background_patterns]
"openai-mcp" = ["pytest", "tox"]

[telemetry.tokenizer]
enabled = true
encoding = "o200k_base"
client_prefixes = ["openai-mcp", "codex"]

[indexed_context]
enabled = true
max_open_indexes = 4

[search_text]
timeout_s = 31
result_max_bytes = 70000
adaptive_discovery_enabled = true
adaptive_detailed_files = 24
adaptive_total_files = 180
adaptive_representative_matches = 3
adaptive_snippet_chars = 220
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
    # The blocking-wall guard's table (removed 2026-09-27) still loads: ignored.
    assert settings.jobs.removed_keys == ("blocking_wall_budget_s_by_client",)
    assert not hasattr(settings.jobs, "blocking_wall_budget_s_by_client")
    assert settings.run_command.auto_background_patterns == {
        "openai-mcp": ("pytest", "tox")
    }
    assert settings.telemetry.tokenizer.enabled is True
    assert settings.telemetry.tokenizer.encoding == "o200k_base"
    assert settings.telemetry.tokenizer.client_prefixes == ("openai-mcp", "codex")
    # The indexed-context pilot's section (removed 2026-09-28) still loads: ignored.
    assert settings.removed_sections == ("indexed_context",)
    assert not hasattr(settings, "indexed_context")
    assert settings.search_text.timeout_s == 31
    assert settings.search_text.result_max_bytes == 70000
    assert settings.search_text.adaptive_discovery_enabled is True
    assert settings.search_text.adaptive_detailed_files == 24
    assert settings.search_text.adaptive_total_files == 180
    assert settings.search_text.adaptive_representative_matches == 3
    assert settings.search_text.adaptive_snippet_chars == 220


def test_run_command_rejects_invalid_auto_background_regex(tmp_path, monkeypatch):
    clear_binnacle_env(monkeypatch)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[run_command.auto_background_patterns]
"openai-mcp" = ["[unterminated"]
"""
    )
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(cfg))

    with pytest.raises(
        ValidationError, match="invalid run_command auto-background regex"
    ):
        config.Settings()


def test_environment_overrides_toml(tmp_path, monkeypatch):
    clear_binnacle_env(monkeypatch)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[serve]
port = 8123

[jobs]
keep_newest = 8

[telemetry.tokenizer]
enabled = false

[indexed_context]
enabled = false
"""
    )
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(cfg))
    monkeypatch.setenv("BINNACLE_SERVE__PORT", "9456")
    monkeypatch.setenv("BINNACLE_JOBS__KEEP_NEWEST", "11")
    monkeypatch.setenv(
        "BINNACLE_JOBS__BLOCKING_WALL_BUDGET_S_BY_CLIENT",
        '{"openai-mcp":120}',
    )
    monkeypatch.setenv("BINNACLE_TELEMETRY__TOKENIZER__ENABLED", "true")
    monkeypatch.setenv("BINNACLE_INDEXED_CONTEXT__ENABLED", "true")

    settings = config.Settings()

    assert settings.serve.port == 9456
    assert settings.jobs.keep_newest == 11
    assert settings.jobs.removed_keys == ("blocking_wall_budget_s_by_client",)
    assert settings.telemetry.tokenizer.enabled is True
    # Neither the removed section nor an environment override for it is an error.
    assert settings.removed_sections == ("indexed_context",)
    assert not hasattr(settings, "indexed_context")


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


def test_search_text_rejects_adaptive_total_below_detailed(tmp_path, monkeypatch):
    clear_binnacle_env(monkeypatch)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[search_text]
adaptive_detailed_files = 30
adaptive_total_files = 20
"""
    )
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(cfg))

    with pytest.raises(
        ValidationError,
        match="adaptive_total_files must be >= adaptive_detailed_files",
    ):
        config.Settings()


def test_run_command_rejects_empty_auto_background_client_key():
    with pytest.raises(
        ValidationError, match="auto_background_patterns keys must be non-empty"
    ):
        config.RunCommandSettings(auto_background_patterns={"": ("pytest",)})


def test_should_auto_background_covers_client_prefix_matching():
    settings = config.RunCommandSettings(
        auto_background_patterns={
            "openai-mcp": (r"pytest", r"tox"),
            "other": (r"never",),
        }
    )

    assert settings.should_auto_background(None, "pytest -q") is False
    assert settings.should_auto_background("openai-mcp(ChatGPT)", "pytest -q") is True
    assert (
        settings.should_auto_background("openai-mcp(ChatGPT)", "python app.py") is False
    )
    assert settings.should_auto_background("unmatched-client", "pytest -q") is False


@pytest.mark.parametrize(
    "table",
    [
        '"openai-mcp" = 300',
        '"openai-mcp" = 0',  # out of the old 1..3600 range: still ignored
        '"" = 120',  # an old blank prefix: still ignored
    ],
)
def test_removed_jobs_blocking_wall_budget_key_is_ignored(table, tmp_path, monkeypatch):
    """The blocking-wall guard was removed on 2026-09-27. A host configuration
    that still has its table keeps loading, whatever the old values were."""
    clear_binnacle_env(monkeypatch)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f"[jobs]\nkeep_newest = 9\n\n[jobs.blocking_wall_budget_s_by_client]\n{table}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(cfg))
    settings = config.Settings()
    assert settings.jobs.keep_newest == 9
    assert settings.jobs.removed_keys == ("blocking_wall_budget_s_by_client",)
    assert not hasattr(settings.jobs, "blocking_wall_budget_s_by_client")


def test_jobs_settings_model_input_keeps_no_removed_keys():
    settings = config.JobsSettings(keep_newest=3)
    assert settings.removed_keys == ()
    assert config.JobsSettings.model_validate(settings).removed_keys == ()


def test_match_auto_background_reports_rule_and_preserves_prefix_order():
    broad_first = config.RunCommandSettings(
        auto_background_patterns={
            "openai": (r"pytest",),
            "openai-mcp": (r"tox",),
        }
    )
    assert broad_first.match_auto_background("openai-mcp", "tox") is None
    match = broad_first.match_auto_background("openai-mcp", "pytest -q")
    assert match == config.AutoBackgroundMatch("openai", r"pytest", 0, 6)

    specific_first = config.RunCommandSettings(
        auto_background_patterns={
            "openai-mcp": (r"tox",),
            "openai": (r"pytest",),
        }
    )
    assert specific_first.match_auto_background(
        "openai-mcp", "tox"
    ) == config.AutoBackgroundMatch("openai-mcp", r"tox", 0, 3)


@pytest.mark.parametrize("days", [0, 1, 14, 365])
def test_run_command_evidence_retention_accepts_bounds(days):
    settings = config.RunCommandSettings(auto_background_evidence_retention_days=days)
    assert settings.auto_background_evidence_retention_days == days


@pytest.mark.parametrize("days", [-1, 366])
def test_run_command_evidence_retention_rejects_out_of_range(days):
    with pytest.raises(ValidationError):
        config.RunCommandSettings(auto_background_evidence_retention_days=days)


def test_removed_run_command_shadow_prediction_section_is_ignored(
    tmp_path, monkeypatch
):
    # The shadow-prediction experiment was removed on 2026-09-27. A host
    # configuration that still has its table (judge keys included) loads.
    clear_binnacle_env(monkeypatch)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[run_command]\n"
        "wait_default_s = 20\n"
        "\n"
        "[run_command.shadow_prediction]\n"
        "enabled = true\n"
        'predictors = ["memory", "rules", "judge"]\n'
        "judge_enabled = true\n"
        "judge_day_budget = 800\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(cfg))

    settings = config.Settings()

    assert settings.run_command.wait_default_s == 20
    assert settings.run_command.removed_sections == ("shadow_prediction",)
    assert not hasattr(settings.run_command, "shadow_prediction")


def test_run_command_without_removed_sections_reports_none(tmp_path, monkeypatch):
    clear_binnacle_env(monkeypatch)
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(tmp_path / "missing.toml"))

    assert config.Settings().run_command.removed_sections == ()
    assert config.RunCommandSettings().removed_sections == ()
    assert (
        config.RunCommandSettings.model_validate(
            config.RunCommandSettings(wait_default_s=12)
        ).wait_default_s
        == 12
    )


@pytest.mark.parametrize(
    "table",
    [
        "enabled = true\nmax_open_indexes = 4",
        'index_dir = "~/.cache/binnacle/indexes"\nreconcile_on_query = false',
        "max_open_indexes = 0\nsnippet_chars = -1",  # invalid for the old model
        "unknown_key = 1",
    ],
)
def test_removed_indexed_context_section_is_ignored(table, tmp_path, monkeypatch):
    """The indexed-context pilot was removed on 2026-09-28. A host configuration
    that still has its section keeps loading, whatever the old values were."""
    clear_binnacle_env(monkeypatch)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f"[search_text]\ntimeout_s = 29\n\n[indexed_context]\n{table}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(cfg))

    settings = config.Settings()

    assert settings.search_text.timeout_s == 29
    assert settings.removed_sections == ("indexed_context",)
    assert not hasattr(settings, "indexed_context")
    assert "indexed_context" not in settings.model_dump()


def test_settings_without_removed_sections_reports_none(tmp_path, monkeypatch):
    clear_binnacle_env(monkeypatch)
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(tmp_path / "missing.toml"))

    settings = config.Settings()

    assert settings.removed_sections == ()
    assert config.Settings.model_validate(settings).removed_sections == ()
    assert config.Settings.model_validate({}).removed_sections == ()
    assert config.Settings.model_validate(
        {"indexed_context": {"enabled": True}}
    ).removed_sections == ("indexed_context",)
    with pytest.raises(ValidationError):
        config.Settings.model_validate(["not", "a", "mapping"])
