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
    assert settings.server.max_request_bytes == 1_048_576
    assert settings.server.session_idle_timeout_seconds == 300.0
    assert settings.server.graceful_shutdown_seconds == 10.0
    assert settings.server.filesystem_stat_timeout_seconds == 2.0


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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_request_bytes", 65_535),
        ("max_request_bytes", 4_194_305),
        ("session_idle_timeout_seconds", 0.0),
        ("session_idle_timeout_seconds", 1_801.0),
        ("session_idle_timeout_seconds", float("inf")),
        ("session_idle_timeout_seconds", float("nan")),
        ("graceful_shutdown_seconds", 0),
        ("graceful_shutdown_seconds", 61),
        ("filesystem_stat_timeout_seconds", 0),
        ("filesystem_stat_timeout_seconds", 11),
    ],
)
def test_phase2_server_bounds_fail_closed(field: str, value: int) -> None:
    with pytest.raises(ValidationError, match=field):
        load_settings(cli_overrides={"server": {field: value}})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_request_bytes", 65_536),
        ("max_request_bytes", 4_194_304),
        ("session_idle_timeout_seconds", 0.001),
        ("session_idle_timeout_seconds", 1_800),
        ("graceful_shutdown_seconds", 0.001),
        ("graceful_shutdown_seconds", 60),
        ("filesystem_stat_timeout_seconds", 0.001),
        ("filesystem_stat_timeout_seconds", 10),
    ],
)
def test_phase2_server_boundaries_are_accepted(field: str, value: float) -> None:
    settings = load_settings(cli_overrides={"server": {field: value}})

    assert getattr(settings.server, field) == value


def test_settings_snapshot_is_immutable() -> None:
    settings = load_settings()

    with pytest.raises(ValidationError, match="frozen"):
        settings.server.port = 9000


def test_model_rejects_unknown_nested_key() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        BinnacleSettings.model_validate({"server": {"unknown": True}})


@pytest.mark.parametrize(
    ("section", "values", "message"),
    [
        ("database", {"path": "/tmp/redirected.db"}, "database path is fixed"),
        ("audit", {"directory": "/tmp/redirected-audit"}, "audit directory is fixed"),
        (
            "payload",
            {"directory": "/tmp/redirected-results"},
            "payload directory is fixed",
        ),
        (
            "payload",
            {"object_bytes_max": 9, "controller_bytes_max": 8},
            "per-object payload limit",
        ),
    ],
)
def test_protected_kernel_paths_and_quota_relationships_cannot_be_redirected(
    section: str, values: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        BinnacleSettings.model_validate({section: values})
