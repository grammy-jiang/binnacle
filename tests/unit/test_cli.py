"""Tests for the Typer/Rich command adapter."""

import json
from pathlib import Path

from typer.testing import CliRunner

from binnacle.application import BinnacleApplication
from binnacle.cli import app
from binnacle.config import ServerSettings

runner = CliRunner()


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


def test_config_validate_invalid_file_exits_nonzero(tmp_path: Path) -> None:
    config_path = tmp_path / "invalid.toml"
    config_path.write_text("unknown = true\n", encoding="utf-8")

    result = runner.invoke(app, ["config", "validate", "--config", str(config_path)])

    assert result.exit_code == 2
    assert "Configuration error" in result.stderr


def test_serve_defaults_to_loopback_one_worker(monkeypatch: object) -> None:
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

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "binnacle.cli.run_http_server",
        fake_run_http_server,
    )

    result = runner.invoke(app, ["serve"])

    assert result.exit_code == 0
    assert observed == {
        "identity": "binnacle",
        "host": "127.0.0.1",
        "port": 8000,
        "workers": 1,
    }


def test_serve_cli_bind_overrides(monkeypatch: object) -> None:
    observed: dict[str, object] = {}

    def fake_run_http_server(
        *,
        application: BinnacleApplication,
        settings: ServerSettings,
    ) -> None:
        del application
        observed.update(host=settings.host, port=settings.port)

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "binnacle.cli.run_http_server",
        fake_run_http_server,
    )

    result = runner.invoke(app, ["serve", "--host", "0.0.0.0", "--port", "9000"])

    assert result.exit_code == 0
    assert observed == {"host": "0.0.0.0", "port": 9000}
