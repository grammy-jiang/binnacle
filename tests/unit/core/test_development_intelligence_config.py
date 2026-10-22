"""P2.0: opt-in feature config is inert, strict and backwards compatible."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from binnacle.config import CONFIG_FILE_ENV, Settings
from binnacle.config_development_intelligence import (
    DevelopmentIntelligenceSettings,
    DevelopmentProviderSettings,
    feature_section_near_miss,
)


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for key in tuple(os.environ):
        if key.startswith("BINNACLE_"):
            monkeypatch.delenv(key)
    path = tmp_path / "config.toml"
    monkeypatch.setenv(CONFIG_FILE_ENV, str(path))
    return path


def test_default_off_has_no_visible_tool_or_profile_cost(cfg: Path) -> None:
    s = Settings()
    assert s.development_intelligence == DevelopmentIntelligenceSettings()
    assert not s.development_intelligence.enabled
    assert not s.development_intelligence.discovery_enabled
    assert s.development_intelligence.profiles == {}
    assert s.client_tools["openai-mcp"] == (
        "read_file",
        "list_files",
        "search_text",
        "run_command",
        "job_status",
        "stop_job",
    )


def test_intentional_on_configuration_is_inert_and_non_executable(cfg: Path) -> None:
    cfg.write_text("""
[development_intelligence]
enabled = true
discovery_enabled = false
max_resident_servers = 3
request_timeout_s = 45
idle_timeout_s = 60

[development_intelligence.profiles.pyright]
enabled = true
source = "service_path"
executable = "pyright-langserver"
argv = ["--stdio"]
languages = ["python"]
mode = "benchmark_only"
""")
    s = Settings()
    d = s.development_intelligence
    assert d.enabled is True
    assert d.max_resident_servers == 3
    assert d.profiles["pyright"].enabled is True
    assert d.profiles["pyright"].executable == "pyright-langserver"
    assert d.profiles["pyright"].argv == ("--stdio",)
    assert s.client_tools["openai-mcp"][0] == "read_file"


def test_environment_can_override_toml_and_nested_provider(
    cfg: Path, monkeypatch
) -> None:
    cfg.write_text("""
[development_intelligence]
enabled = false
max_resident_servers = 2

[development_intelligence.profiles.pyright]
enabled = false
""")
    monkeypatch.setenv("BINNACLE_DEVELOPMENT_INTELLIGENCE__ENABLED", "true")
    monkeypatch.setenv("BINNACLE_DEVELOPMENT_INTELLIGENCE__MAX_RESIDENT_SERVERS", "3")
    monkeypatch.setenv(
        "BINNACLE_DEVELOPMENT_INTELLIGENCE__PROFILES__PYRIGHT__ENABLED", "true"
    )
    result = Settings().development_intelligence
    assert result.enabled is True
    assert result.max_resident_servers == 3
    assert result.profiles["pyright"].enabled is True


@pytest.mark.parametrize(
    "name",
    [
        "development_intellignece",
        "development_intellegence",
        "developement_intelligence",
    ],
)
def test_feature_table_typos_fail_closed(cfg: Path, name: str) -> None:
    assert feature_section_near_miss(name)
    cfg.write_text(f"[{name}]\nenabled = true\n")
    with pytest.raises(ValidationError, match="development_intelligence-like"):
        Settings()


@pytest.mark.parametrize(
    "name",
    [
        "BINNACLE_DEVELOPMENT_INTELLIGNECE__ENABLED",
        "BINNACLE_DEVELOPMENT_INTELLEGENCE__ENABLED",
    ],
)
def test_feature_env_typos_fail_closed(cfg: Path, monkeypatch, name: str) -> None:
    monkeypatch.setenv(name, "true")
    with pytest.raises(ValidationError, match="development_intelligence-like"):
        Settings()


@pytest.mark.parametrize(
    ("source", "fragment"),
    [
        ("[development_intelligence]\nenabld = true\n", "enabld"),
        ("[development_intelligence]\nenabled = false\nbogus = 1\n", "bogus"),
        (
            "[development_intelligence.profiles.pyright]\nunrecognized_option = true\n",
            "unrecognized_option",
        ),
        (
            "[development_intelligence.profiles.fake_pyright]\nenabled = true\n",
            "fake_pyright",
        ),
    ],
)
def test_unknown_feature_or_provider_keys_rejected_when_off(
    cfg: Path, source: str, fragment: str
) -> None:
    cfg.write_text(source)
    with pytest.raises(ValidationError, match=fragment):
        Settings()


@pytest.mark.parametrize(
    "var",
    [
        "BINNACLE_DEVELOPMENT_INTELLIGENCE__WRONG_KEY",
        "BINNACLE_DEVELOPMENT_INTELLIGENCE__PROFILES__PYRIGHT__WRONG_FIELD",
    ],
)
def test_unknown_nested_env_keys_rejected(cfg: Path, monkeypatch, var: str) -> None:
    monkeypatch.setenv(var, "true")
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "section",
    [
        "[development_intelligence]\nenabled = 1\n",
        '[development_intelligence]\nenabled = "yes"\n',
        "[development_intelligence]\nmax_resident_servers = 0\n",
        "[development_intelligence]\nmax_resident_servers = 99\n",
        '[development_intelligence]\nmax_resident_servers = "4.0"\n',
        "[development_intelligence]\nrequest_timeout_s = 0\n",
        "[development_intelligence]\nrequest_timeout_s = 3600\n",
        "[development_intelligence]\nidle_timeout_s = -1\n",
        "[development_intelligence.profiles.pyright]\nenabled = 1\n",
    ],
)
def test_invalid_types_ranges_even_when_disabled(cfg: Path, section: str) -> None:
    cfg.write_text(section)
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "executable",
    [
        "./.venv/bin/pyright",
        "../node_modules/.bin/pyright",
        "/usr/bin/pyright",
        "foo/bar",
        "..",
        "$HOME/bin/pyright",
    ],
)
def test_service_path_never_accepts_project_or_absolute_executable(
    executable: str,
) -> None:
    with pytest.raises(ValidationError, match="bare name"):
        DevelopmentProviderSettings(executable=executable)


def test_explicit_absolute_requires_explicit_trust_no_provider_probe(cfg: Path) -> None:
    with pytest.raises(ValidationError, match="explicit_trust_only"):
        DevelopmentProviderSettings(
            source="trusted_absolute",
            executable="/nonexistent/program",
            mode="benchmark_only",
        )
    declared = DevelopmentProviderSettings(
        source="trusted_absolute",
        executable="/nonexistent/program",
        mode="explicit_trust_only",
    )
    # Configuration is only data; it does not require the binary to exist.
    assert declared.executable == "/nonexistent/program"
    with pytest.raises(ValidationError, match="absolute path"):
        DevelopmentProviderSettings(
            source="trusted_absolute",
            executable="bin/pyright",
            mode="explicit_trust_only",
        )


@pytest.mark.parametrize("name", ["PATH", "PYTHONPATH", "LD_PRELOAD"])
def test_profile_rejects_process_resolver_env_overrides(name: str) -> None:
    with pytest.raises(ValidationError, match="forbidden"):
        DevelopmentProviderSettings(env={name: "/workspace/bin"})


def test_unrelated_legacy_section_remains_ignored(cfg: Path) -> None:
    cfg.write_text("""
[watchdog]
driver_reload_enabled = true
[arbitrary_other_feature]
enabled = true
""")
    s = Settings()
    assert s.development_intelligence.enabled is False


def test_nested_models_are_isolated_from_each_settings_instance(cfg: Path) -> None:
    first = Settings()
    second = Settings()
    first.development_intelligence.profiles["pyright"] = DevelopmentProviderSettings()
    assert second.development_intelligence.profiles == {}


def test_opt_in_flag_does_not_register_mcp_tools_before_p2_7(cfg: Path) -> None:
    """P2.0 is config only; both client surfaces retain exact schema and order."""
    from binnacle.application import create_application
    from tests.command_support import MemoryCommands
    from tests.contracts.surface_support import served, surface

    def snapshot(enabled: bool, client: str | None) -> tuple:
        setting = Settings(development_intelligence={"enabled": enabled})
        root = create_application(
            settings=setting,
            token="synthetic-opt-in-test",
            backend=MemoryCommands("unused"),
        )
        tools, instructions = served(client, mcp_server=root)
        return tuple(surface(tool) for tool in tools), instructions

    for client, expected in ((None, 8), ("openai-mcp(ChatGPT)", 6)):
        disabled = snapshot(False, client)
        opted_in_but_unmounted = snapshot(True, client)
        assert disabled == opted_in_but_unmounted
        assert len(disabled[0]) == expected
        assert not any("symbol" in tool["name"] for tool in disabled[0])


def test_provider_discovery_cannot_be_enabled_when_feature_is_off(cfg: Path) -> None:
    cfg.write_text("[development_intelligence]\ndiscovery_enabled = true\n")
    with pytest.raises(ValidationError, match="requires enabled=true"):
        Settings()


def test_config_cannot_claim_provider_audited_read_safety(cfg: Path) -> None:
    # Provider safety is earned by later audits, not by a TOML option.
    with pytest.raises(ValidationError):
        DevelopmentProviderSettings(mode="audited_read_eligible")
