"""Startup WARNING for removed configuration sections and keys.

Removed on 2026-09-27: the run_command shadow-prediction experiment and the
jobs blocking-wall guard; on 2026-09-28: the indexed-context pilot (the
top-level [indexed_context] section). A host configuration that still has
any of these tables must load and say so once.
"""

from binnacle import server


def test_removed_config_section_is_named_once_at_startup(caplog, monkeypatch, tmp_path):
    """An old [run_command.shadow_prediction] table gives one WARNING line."""
    from binnacle import config

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[run_command.shadow_prediction]\nenabled = true\n", encoding="utf-8"
    )
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(cfg))
    settings = config.Settings()
    monkeypatch.setattr(server, "get_settings", lambda: settings)
    with caplog.at_level("INFO", logger="binnacle.server"):
        server.log_effective_config()
    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.levelname == "WARNING" and "event=config_warning" in r.getMessage()
    ]
    assert warnings == [
        (
            "event=config_warning section=run_command.shadow_prediction "
            "reason=removed action=ignored"
        )
    ]


def test_removed_jobs_key_is_named_once_at_startup(caplog, monkeypatch, tmp_path):
    """An old [jobs.blocking_wall_budget_s_by_client] table gives one WARNING line."""
    from binnacle import config

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[jobs.blocking_wall_budget_s_by_client]\n"openai-mcp" = 300\n',
        encoding="utf-8",
    )
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(cfg))
    settings = config.Settings()
    monkeypatch.setattr(server, "get_settings", lambda: settings)
    with caplog.at_level("INFO", logger="binnacle.server"):
        server.log_effective_config()
    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.levelname == "WARNING" and "event=config_warning" in r.getMessage()
    ]
    assert warnings == [
        (
            "event=config_warning section=jobs.blocking_wall_budget_s_by_client "
            "reason=removed action=ignored"
        )
    ]


def test_removed_indexed_context_section_is_named_once_at_startup(
    caplog, monkeypatch, tmp_path
):
    """An old [indexed_context] section gives one WARNING line, and the
    event=config line no longer carries the pilot's fields."""
    from binnacle import config

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[indexed_context]\nenabled = true\nmax_open_indexes = 4\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(cfg))
    settings = config.Settings()
    monkeypatch.setattr(server, "get_settings", lambda: settings)
    with caplog.at_level("INFO", logger="binnacle.server"):
        server.log_effective_config()
    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.levelname == "WARNING" and "event=config_warning" in r.getMessage()
    ]
    assert warnings == [
        "event=config_warning section=indexed_context reason=removed action=ignored"
    ]
    config_lines = [
        r.getMessage()
        for r in caplog.records
        if r.getMessage().startswith("event=config ")
    ]
    assert len(config_lines) == 1
    assert "indexed" not in config_lines[0]


def test_effective_config_line_names_no_removed_section(caplog, monkeypatch, tmp_path):
    from binnacle import config

    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(tmp_path / "missing.toml"))
    with caplog.at_level("INFO", logger="binnacle.server"):
        server.log_effective_config()
    assert not [r for r in caplog.records if "event=config_warning" in r.getMessage()]
    assert "shadow_prediction" not in caplog.text
    assert "blocking_wall" not in caplog.text
    assert "indexed_context" not in caplog.text
