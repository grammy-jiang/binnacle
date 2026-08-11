"""Tests for trusted Phase 2 composition and fatal startup boundaries."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from tests.conftest import FakeDeviceIdentityProvider, FakeSystemInspector

from binnacle.composition import compose_application
from binnacle.config import BinnacleSettings, load_settings
from binnacle.contracts import ContractRegistry, ContractRegistryError
from binnacle.domain.runtime import BuildIdentity
from binnacle.logging import LoggingRuntime


class RecordingLogger:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict[str, Any]]] = []

    def info(self, event: str, **values: Any) -> None:
        self.records.append(("info", event, values))

    def error(self, event: str, **values: Any) -> None:
        self.records.append(("error", event, values))


def _logging_runtime() -> LoggingRuntime:
    return LoggingRuntime(handler=logging.NullHandler())


def _stub_host_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "binnacle.composition.compute_build_identity",
        lambda *, version: BuildIdentity(version=version, build_sha256="a" * 64),
    )
    monkeypatch.setattr(
        "binnacle.composition.LinuxDeviceIdentityProvider",
        FakeDeviceIdentityProvider,
    )
    monkeypatch.setattr(
        "binnacle.composition.LinuxSystemInspector",
        lambda *, filesystem_stat_timeout_seconds: FakeSystemInspector(),
    )


@pytest.mark.anyio
async def test_compose_builds_exact_readonly_graph_and_closes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _logging_runtime()
    logger = RecordingLogger()
    monkeypatch.setattr("binnacle.composition.configure_logging", lambda _settings: runtime)
    monkeypatch.setattr("binnacle.composition._LOGGER", logger)
    _stub_host_adapters(monkeypatch)

    composed = compose_application(settings=load_settings())

    assert tuple(composed.contracts.tools) == (
        "binnacle_probe",
        "system_inspect",
        "probe_result_formats",
        "probe_error",
        "compatibility_report",
    )
    assert composed.application.contracts is composed.contracts
    loaded = next(record for record in logger.records if record[1] == "contract_registry_loaded")
    assert loaded[2]["registered_tool_count"] == 5
    assert len(loaded[2]["manifest_sha256_prefix"]) == 12
    assert len(loaded[2]["catalogue_sha256_prefix"]) == 12

    await composed.close()
    await composed.close()

    assert runtime._closed is True


def test_registry_integrity_failure_closes_logging_and_aborts_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _logging_runtime()
    logger = RecordingLogger()
    monkeypatch.setattr("binnacle.composition.configure_logging", lambda _settings: runtime)
    monkeypatch.setattr("binnacle.composition._LOGGER", logger)

    def fail_load() -> ContractRegistry:
        raise ContractRegistryError("fixture registry content that must not be logged")

    monkeypatch.setattr(ContractRegistry, "load", staticmethod(fail_load))

    with pytest.raises(ContractRegistryError, match="fixture registry"):
        compose_application(settings=BinnacleSettings())

    assert runtime._closed is True
    assert logger.records == [
        (
            "error",
            "contract_registry_load_failed",
            {"error_type": "ContractRegistryError"},
        )
    ]
