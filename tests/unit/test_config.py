"""Tests for immutable settings and source precedence."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from binnacle.config import BinnacleSettings, EnvironmentNamespaceError, load_settings


def test_default_settings_are_development_loopback() -> None:
    settings = load_settings()

    assert settings.runtime_profile == "development"
    assert settings.server.host == "127.0.0.1"
    assert settings.server.workers == 1


def test_toml_overrides_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "binnacle.toml"
    config_path.write_text(
        '[server]\nhost = "localhost"\nport = 9000\n\n[logging]\nlevel = "DEBUG"\n',
        encoding="utf-8",
    )

    settings = load_settings(config_path=config_path)

    assert settings.server.host == "localhost"
    assert settings.server.port == 9000
    assert settings.logging.level == "DEBUG"


def test_environment_overrides_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "binnacle.toml"
    config_path.write_text("[server]\nport = 9000\n", encoding="utf-8")
    monkeypatch.setenv("BINNACLE_SERVER__PORT", "9100")

    settings = load_settings(config_path=config_path)

    assert settings.server.port == 9100


def test_nested_environment_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BINNACLE_LOGGING__LEVEL", "WARNING")
    monkeypatch.setenv("BINNACLE_LOGGING__FORMAT", "json")

    settings = load_settings()

    assert settings.logging.level == "WARNING"
    assert settings.logging.format == "json"


def test_cli_override_wins_for_ordinary_server_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "binnacle.toml"
    config_path.write_text(
        '[server]\nhost = "toml.example"\nport = 9000\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("BINNACLE_SERVER__HOST", "env.example")
    monkeypatch.setenv("BINNACLE_SERVER__PORT", "9100")

    settings = load_settings(
        config_path=config_path,
        cli_overrides={"server": {"host": "cli.example", "port": 9200}},
    )

    assert settings.server.host == "cli.example"
    assert settings.server.port == 9200


def test_cli_override_replaces_invalid_lower_priority_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BINNACLE_SERVER__PORT", "invalid")

    settings = load_settings(cli_overrides={"server": {"port": 9200}})

    assert settings.server.port == 9200


def test_unknown_toml_key_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "binnacle.toml"
    config_path.write_text("unknown = true\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="unknown"):
        load_settings(config_path=config_path)


@pytest.mark.parametrize(
    "name",
    [
        "BINNACLE_UNKNOWN",
        "BINNACLE_SERVER__PRT",
        "BINNACLE_LOGGING__LEVEL__EXTRA",
    ],
)
def test_unknown_environment_key_is_rejected(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(name, "not-observed")

    with pytest.raises(EnvironmentNamespaceError, match="unknown BINNACLE"):
        load_settings()


@pytest.mark.parametrize("port", [0, 65536])
def test_invalid_port_is_rejected(port: int) -> None:
    with pytest.raises(ValidationError, match="port"):
        load_settings(cli_overrides={"server": {"port": port}})


def test_settings_snapshot_is_immutable() -> None:
    settings = load_settings()

    with pytest.raises(ValidationError, match="frozen"):
        settings.server.port = 9000


def test_model_rejects_unknown_nested_key() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        BinnacleSettings.model_validate({"server": {"unknown": True}})
