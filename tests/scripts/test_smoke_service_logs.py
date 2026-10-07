"""G4 service-log failure and composition regressions for the live smoke."""

from pathlib import Path

import pytest

from binnacle.platform.contracts.service_log_contracts import ServiceLogError
from scripts import deploy_smoke
from scripts.smoke_checks import smoke
from tests.scripts.test_smoke_checks import FakeClient, journal_for, levels, make_env


@pytest.mark.parametrize(
    "detail", ["journalctl failed: denied", "journalctl timed out after 60 s"]
)
def test_required_journal_failure_is_alert_not_exception(
    tmp_path: Path, detail: str
) -> None:
    def broken_journal(since: float, until: float | None) -> list[str]:
        raise ServiceLogError(detail)

    report = smoke(make_env(tmp_path, FakeClient(), journal=broken_journal))

    assert report.level == "alert"
    assert levels(report)["journal"] == "alert"
    assert levels(report)["startup_s"] == "alert"
    assert any(detail in check.detail for check in report.checks)


@pytest.mark.parametrize(
    "detail", ["journalctl failed: denied", "journalctl timed out after 60 s"]
)
def test_startup_window_journal_failure_is_alert(tmp_path: Path, detail: str) -> None:
    client = FakeClient()
    normal = journal_for(client)

    def journal(since: float, until: float | None) -> list[str]:
        if until is not None:
            raise ServiceLogError(detail)
        return normal(since, until)

    report = smoke(make_env(tmp_path, client, journal=journal))

    assert levels(report)["journal"] == "ok"
    assert levels(report)["startup_s"] == "alert"
    assert detail in next(
        check.detail for check in report.checks if check.name == "startup_s"
    )


def test_deploy_journal_composition_needs_only_semantic_read_window(monkeypatch):
    seen = {}

    class EpochOnlySource:
        def read_window(self, services, since_epoch, until_epoch=None):
            seen.update(
                services=tuple(services),
                since=since_epoch,
                until=until_epoch,
            )
            return "a\nb\n"

    def factory(*, command_timeout_s):
        seen["timeout"] = command_timeout_s
        return EpochOnlySource()

    monkeypatch.setattr(deploy_smoke, "create_service_log_source", factory)

    assert deploy_smoke.read_journal(10.9, 20.1) == ["a", "b"]
    assert seen == {
        "timeout": 60.0,
        "services": ("binnacle-mcp.service",),
        "since": 10.9,
        "until": 20.1,
    }
