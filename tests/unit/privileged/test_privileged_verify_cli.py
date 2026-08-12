"""Installed read-only verifier entrypoint tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from binnacle.privileged_broker import verify_cli
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
    monkeypatch.setattr(verify_cli, "verify_installed_database", _report)

    assert verify_cli.main(["--require-default-disabled", "--output", "json"]) == 0
    output = capsys.readouterr()
    assert '"readiness":"disabled"' in output.out
    assert output.err == ""


def test_installed_verifier_cli_fails_closed_without_disclosure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = replace(_report(), readiness="restricted_recovery", accepted_bindings=1)
    monkeypatch.setattr(verify_cli, "verify_installed_database", lambda: report)

    assert verify_cli.main(["--require-default-disabled"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "Privileged-broker verification failed: InstalledPrivilegedVerificationError\n"
    )
