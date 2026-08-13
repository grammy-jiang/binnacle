from __future__ import annotations

from pathlib import Path

import pytest

from binnacle.privileged_broker import __main__ as main_module


def test_privileged_main_runs_only_the_fixed_default_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[Path] = []

    async def run(config_path: Path) -> None:
        observed.append(config_path)

    monkeypatch.setattr(main_module, "run_privileged_broker_service", run)

    assert main_module.main([]) == 0
    assert observed == [Path("/etc/binnacle-privileged/broker.toml")]


def test_privileged_main_sanitizes_service_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def fail(_config_path: Path) -> None:
        raise RuntimeError("sensitive fixture detail")

    monkeypatch.setattr(main_module, "run_privileged_broker_service", fail)

    assert main_module.main([]) == 1
    assert capsys.readouterr().err == "Privileged broker failed: RuntimeError\n"
