"""Tests for the Typer/Rich command adapter."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from binnacle import cli
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
        operation_kernel_factory: object,
    ) -> None:
        observed["identity"] = application.identity.distribution_name
        observed["host"] = settings.host
        observed["port"] = settings.port
        observed["workers"] = settings.workers
        observed["kernel_factory"] = callable(operation_kernel_factory)

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
        "kernel_factory": True,
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
        operation_kernel_factory: object,
    ) -> None:
        del application
        observed.update(
            host=settings.host,
            port=settings.port,
            kernel_factory=callable(operation_kernel_factory),
        )

    monkeypatch.setattr("binnacle.cli.run_http_server", fake_run_http_server)
    _stub_composition(monkeypatch, phase2_application)

    result = runner.invoke(app, ["serve", "--host", "::1", "--port", "9000"])

    assert result.exit_code == 0
    assert observed == {"host": "::1", "port": 9000, "kernel_factory": True}


def test_database_upgrade_reports_success_and_sanitized_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def succeed(settings: object, *, project_root: Path) -> None:
        observed["settings"] = settings
        observed["project_root"] = project_root

    monkeypatch.setattr(cli, "upgrade_database", succeed)
    result = runner.invoke(app, ["db", "upgrade"])
    assert result.exit_code == 0
    assert result.stdout == "Database upgraded to 0002_write_probe_state\n"
    assert observed["project_root"] == Path(cli.__file__).resolve().parents[2]

    def fail(settings: object, *, project_root: Path) -> None:
        del settings, project_root
        raise RuntimeError("secret database detail")

    monkeypatch.setattr(cli, "upgrade_database", fail)
    result = runner.invoke(app, ["db", "upgrade"])
    assert result.exit_code == 1
    assert result.stderr == "Database upgrade failed: RuntimeError\n"
    assert "secret" not in result.stderr


def test_database_status_renders_and_sanitizes_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = SimpleNamespace(
        revision="0002_write_probe_state",
        journal_mode="wal",
        synchronous=2,
        foreign_keys=1,
        busy_timeout_ms=5000,
        wal_autocheckpoint_pages=1000,
    )
    monkeypatch.setattr(cli, "verify_database_read_only", lambda **_kwargs: status)
    result = runner.invoke(app, ["db", "status", "--output", "json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["revision"] == "0002_write_probe_state"

    def fail(**_kwargs: object) -> object:
        raise OSError("secret database path")

    monkeypatch.setattr(cli, "verify_database_read_only", fail)
    result = runner.invoke(app, ["db", "status"])
    assert result.exit_code == 1
    assert result.stderr == "Database status failed: OSError\n"


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("json", '"availability":"available"'),
        ("agent", "availability=available audit_sequence=7 obligation_count=0"),
        ("human", "Kernel available; audit sequence 7; obligations 0"),
    ],
)
def test_kernel_verify_renders_all_modes(
    monkeypatch: pytest.MonkeyPatch, mode: str, expected: str
) -> None:
    async def healthy(settings: BinnacleSettings) -> dict[str, object]:
        del settings
        return {
            "availability": "available",
            "database_healthy": True,
            "audit_healthy": True,
            "payload_healthy": True,
            "audit_failure_latched": False,
            "obligation_count": 0,
            "reason_codes": [],
            "audit_sequence": 7,
        }

    monkeypatch.setattr(cli, "_kernel_health", healthy)
    result = runner.invoke(app, ["kernel", "verify", "--output", mode])
    assert result.exit_code == 0
    assert expected in result.stdout


def test_kernel_verify_unavailable_and_exception_exit_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unavailable(settings: BinnacleSettings) -> dict[str, object]:
        del settings
        return {
            "availability": "unavailable",
            "database_healthy": True,
            "audit_healthy": False,
            "payload_healthy": True,
            "audit_failure_latched": True,
            "obligation_count": 1,
            "audit_obligation_count": 1,
            "audit_obligation_matched": 0,
            "audit_obligation_unmatched": 1,
            "audit_failure_generation": 2,
            "audit_recovered_generation": 1,
            "reason_codes": ["audit_recovery_required"],
            "audit_sequence": 3,
        }

    monkeypatch.setattr(cli, "_kernel_health", unavailable)
    result = runner.invoke(app, ["audit", "verify", "--output", "agent"])
    assert result.exit_code == 1
    assert "status=fail" in result.stdout
    assert "unmatched=1" in result.stdout

    async def fail(settings: BinnacleSettings) -> dict[str, object]:
        del settings
        raise OSError("secret path")

    monkeypatch.setattr(cli, "_kernel_health", fail)
    result = runner.invoke(app, ["kernel", "verify"])
    assert result.exit_code == 1
    assert result.stderr == "Kernel verification failed: OSError\n"


def test_kernel_health_uses_read_only_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeReport:
        def as_dict(self) -> dict[str, object]:
            return {"audit_sequence": 9, "reason_codes": ["fixture"]}

    async def verify(**kwargs: object) -> FakeReport:
        assert kwargs["busy_timeout_ms"] == 5000
        return FakeReport()

    monkeypatch.setattr(cli, "verify_operation_kernel_read_only", verify)
    health = __import__("asyncio").run(cli._kernel_health(BinnacleSettings()))
    assert health["audit_sequence"] == 9
    assert health["reason_codes"] == ["fixture"]


def test_audit_closure_file_validation_and_recovery_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closure_file = tmp_path / "closures.json"
    closure_file.write_text(
        json.dumps(
            {
                "generation": 3,
                "closures": [
                    {
                        "obligation_id": "obl-fixture",
                        "effect_outcome": "known_no_effect",
                        "evidence_sha256": "a" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    generation, closures = cli._load_audit_closures(closure_file)
    assert generation == 3
    assert closures[0].obligation_id == "obl-fixture"

    async def recover(
        settings: BinnacleSettings,
        selected_generation: int,
        selected_closures: tuple[object, ...],
    ) -> str:
        del settings
        assert selected_generation == 3
        assert len(selected_closures) == 1
        return "b" * 64

    monkeypatch.setattr(cli, "_recover_audit", recover)
    command = [
        "audit",
        "recover",
        "--generation",
        "3",
        "--closure-file",
        str(closure_file),
    ]
    result = runner.invoke(app, command)
    assert result.exit_code == 0
    assert "generation 3 recovered" in result.stdout
    assert "b" * 64 in result.stdout

    for invalid in (
        "not-json",
        '{"generation":0,"closures":[]}',
        '{"generation":1,"closures":["bad"]}',
        '{"generation":1}',
    ):
        closure_file.write_text(invalid, encoding="utf-8")
        with pytest.raises(ValueError, match="invalid audit recovery"):
            cli._load_audit_closures(closure_file)

    result = runner.invoke(app, command)
    assert result.exit_code == 1
    assert result.stderr == "Audit recovery failed: ValueError\n"
