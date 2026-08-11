"""Tests for the Typer/Rich command adapter."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from binnacle.application import BinnacleApplication
from binnacle.cli import app
from binnacle.config import BinnacleSettings, ServerSettings

runner = CliRunner()


class _FakeComposed:
    def __init__(self, application: BinnacleApplication) -> None:
        self.application = application

    async def close(self) -> None:
        return None


def _stub_composition(
    monkeypatch: pytest.MonkeyPatch,
    application: BinnacleApplication,
) -> None:
    def fake_compose(*, settings: BinnacleSettings) -> _FakeComposed:
        del settings
        return _FakeComposed(application)

    monkeypatch.setattr("binnacle.cli.compose_application", fake_compose)


def test_version_human() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "Binnacle" in result.stdout


def test_version_agent_is_plain_deterministic_text() -> None:
    result = runner.invoke(app, ["version", "--output", "agent"])

    assert result.exit_code == 0
    assert result.stdout.startswith("distribution_name=binnacle version=")
    assert "\x1b" not in result.stdout


def test_version_json_is_single_json_document() -> None:
    result = runner.invoke(app, ["version", "--output", "json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["distribution_name"] == "binnacle"
    assert result.stdout.count("\n") == 1


def test_config_validate_json() -> None:
    result = runner.invoke(app, ["config", "validate", "--output", "json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "valid"


def test_config_validate_agent_is_plain_text() -> None:
    result = runner.invoke(app, ["config", "validate", "--output", "agent"])

    assert result.exit_code == 0
    assert result.stdout.startswith("status=valid runtime_profile=development")


def test_config_validate_invalid_file_exits_nonzero(tmp_path: Path) -> None:
    config_path = tmp_path / "invalid.toml"
    config_path.write_text("unknown = true\n", encoding="utf-8")

    result = runner.invoke(app, ["config", "validate", "--config", str(config_path)])

    assert result.exit_code == 2
    assert "Configuration error" in result.stderr


def test_config_validate_invalid_toml_is_sanitized(tmp_path: Path) -> None:
    config_path = tmp_path / "invalid.toml"
    config_path.write_text("port = [", encoding="utf-8")

    result = runner.invoke(app, ["config", "validate", "--config", str(config_path)])

    assert result.exit_code == 2
    assert result.stderr == "Configuration error: invalid TOML syntax\n"


def test_config_validate_unreadable_file_is_sanitized(tmp_path: Path) -> None:
    config_path = tmp_path / "missing.toml"

    result = runner.invoke(app, ["config", "validate", "--config", str(config_path)])

    assert result.exit_code == 2
    assert result.stderr == "Configuration error: configuration file could not be read\n"


def test_config_validation_redacts_invalid_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_value = "accidental-secret-value"
    monkeypatch.setenv("BINNACLE_LOGGING__LEVEL", secret_value)

    result = runner.invoke(app, ["config", "validate"])

    assert result.exit_code == 2
    assert "logging.level" in result.stderr
    assert secret_value not in result.stderr


def test_config_validation_redacts_untrusted_location_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    untrusted_key = "\nTOKEN=accidental-secret-name"
    secret_value = "accidental-secret-value"
    monkeypatch.setenv("BINNACLE_SERVER", json.dumps({untrusted_key: secret_value}))

    result = runner.invoke(app, ["config", "validate"])

    assert result.exit_code == 2
    assert "server.<unknown>" in result.stderr
    assert result.stderr.count("\n") == 1
    assert untrusted_key not in result.stderr
    assert secret_value not in result.stderr


def test_config_validation_sanitizes_environment_source_parse_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_value = "not-json-accidental-secret"
    monkeypatch.setenv("BINNACLE_SERVER", secret_value)

    result = runner.invoke(app, ["config", "validate"])

    assert result.exit_code == 2
    assert result.stderr == "Configuration error: server: invalid environment value\n"
    assert secret_value not in result.stderr
    assert result.exception is not None


def test_config_validation_rejects_unknown_environment_key_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unknown_name = "BINNACLE_SERVER__ACCIDENTAL_SECRET_NAME"
    secret_value = "accidental-secret-value"
    monkeypatch.setenv(unknown_name, secret_value)

    result = runner.invoke(app, ["config", "validate"])

    assert result.exit_code == 2
    assert result.stderr == "Configuration error: unknown BINNACLE_* environment setting\n"
    assert unknown_name not in result.stderr
    assert secret_value not in result.stderr


def test_serve_defaults_to_loopback_one_worker(
    monkeypatch: pytest.MonkeyPatch,
    phase2_application: BinnacleApplication,
) -> None:
    observed: dict[str, object] = {}

    def fake_run_http_server(
        *,
        application: BinnacleApplication,
        settings: ServerSettings,
    ) -> None:
        observed["identity"] = application.identity.distribution_name
        observed["host"] = settings.host
        observed["port"] = settings.port
        observed["workers"] = settings.workers

    monkeypatch.setattr(
        "binnacle.cli.run_http_server",
        fake_run_http_server,
    )
    _stub_composition(monkeypatch, phase2_application)

    result = runner.invoke(app, ["serve"])

    assert result.exit_code == 0
    assert observed == {
        "identity": "binnacle",
        "host": "127.0.0.1",
        "port": 8000,
        "workers": 1,
    }


def test_serve_rejects_nonloopback_before_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composed = False

    def unexpected_compose(*, settings: BinnacleSettings) -> _FakeComposed:
        del settings
        nonlocal composed
        composed = True
        raise AssertionError("composition must not run")

    monkeypatch.setattr("binnacle.cli.compose_application", unexpected_compose)

    result = runner.invoke(app, ["serve", "--host", "0.0.0.0", "--port", "9000"])

    assert result.exit_code == 2
    assert "canonical loopback" in result.stderr
    assert composed is False


def test_serve_accepts_ipv6_loopback_override(
    monkeypatch: pytest.MonkeyPatch,
    phase2_application: BinnacleApplication,
) -> None:
    observed: dict[str, object] = {}

    def fake_run_http_server(
        *,
        application: BinnacleApplication,
        settings: ServerSettings,
    ) -> None:
        del application
        observed.update(host=settings.host, port=settings.port)

    monkeypatch.setattr("binnacle.cli.run_http_server", fake_run_http_server)
    _stub_composition(monkeypatch, phase2_application)

    result = runner.invoke(app, ["serve", "--host", "::1", "--port", "9000"])

    assert result.exit_code == 0
    assert observed == {"host": "::1", "port": 9000}
