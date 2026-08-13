"""Installed read-only verifier entrypoint tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from binnacle.privileged_broker import verify_cli
from binnacle.privileged_broker.artifact import PrivilegedArtifactError
from binnacle.privileged_broker.config import (
    DEFAULT_PRIVILEGED_CONFIG_PATH,
    PrivilegedBrokerSettings,
)
from binnacle.privileged_broker.integrity import PrivilegedBrokerIntegrityReport


def _report() -> PrivilegedBrokerIntegrityReport:
    return PrivilegedBrokerIntegrityReport(
        revision="0001_privileged_evidence",
        readiness="disabled",
        schema_generation=1,
        evidence_generation=0,
        unresolved_bindings=0,
        accepted_bindings=0,
        outstanding_accepted_bindings=0,
        sealed_bindings=0,
        active_subeffects=0,
        uncertain_subeffects=0,
        package_plans=0,
        runtime_slots=0,
        restart_checkpoints=0,
        selector_generations=0,
    )


def test_installed_verifier_cli_reports_sanitized_default_disabled_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(verify_cli, "verify_installed_boundary", _report)

    assert verify_cli.main(["--require-default-disabled", "--output", "json"]) == 0
    output = capsys.readouterr()
    assert '"readiness":"disabled"' in output.out
    assert output.err == ""


def test_installed_verifier_cli_fails_closed_without_disclosure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = replace(_report(), readiness="restricted_recovery", accepted_bindings=1)
    monkeypatch.setattr(verify_cli, "verify_installed_boundary", lambda: report)

    assert verify_cli.main(["--require-default-disabled"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "Privileged-broker verification failed: InstalledPrivilegedVerificationError\n"
    )


def test_installed_boundary_binds_config_artifact_and_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Path("/var/lib/binnacle-privileged/evidence.db")
    settings = PrivilegedBrokerSettings(
        database_path=database,
        runtime_directory=Path("/run/binnacle-privileged"),
        runtime_group_gid=1001,
        expected_application_uid=1002,
        expected_application_gid=1003,
        build_sha256="a" * 64,
        profile_sha256="b" * 64,
        acceptance_enabled=False,
    )
    events: list[object] = []
    report = _report()

    def load(path: Path) -> PrivilegedBrokerSettings:
        events.append(("config", path))
        return settings

    def verify_artifact(*, expected_build_sha256: str) -> None:
        events.append(("artifact", expected_build_sha256))

    def verify_database(path: Path) -> PrivilegedBrokerIntegrityReport:
        events.append(("database", path))
        return report

    monkeypatch.setattr(
        verify_cli,
        "load_privileged_broker_settings",
        load,
    )
    monkeypatch.setattr(
        verify_cli,
        "verify_privileged_artifact",
        verify_artifact,
    )
    monkeypatch.setattr(
        verify_cli,
        "verify_installed_database",
        verify_database,
    )

    assert verify_cli.verify_installed_boundary() is report
    assert events == [
        ("config", DEFAULT_PRIVILEGED_CONFIG_PATH),
        ("artifact", "a" * 64),
        ("database", database),
    ]


def test_installed_verifier_cli_sanitizes_artifact_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail() -> PrivilegedBrokerIntegrityReport:
        raise PrivilegedArtifactError("sensitive artifact detail")

    monkeypatch.setattr(verify_cli, "verify_installed_boundary", fail)

    assert verify_cli.main([]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "Privileged-broker verification failed: PrivilegedArtifactError\n"
