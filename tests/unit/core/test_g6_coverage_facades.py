"""Exercise relocated public facades without changing per-module coverage floors."""

from __future__ import annotations

import importlib
import importlib.util

import pytest


@pytest.mark.parametrize(
    ("legacy", "canonical"),
    [
        ("binnacle.diagnostics.doctor_contracts", "binnacle.doctor_contracts"),
        ("binnacle.job_manager", "binnacle.features.commands.job_manager"),
        *(
            (f"binnacle.{name}", f"binnacle.observability.{name}")
            for name in (
                "logstats_adaptive",
                "logstats_jobs",
                "logstats_models",
                "logstats_parse",
                "logstats_run_command_groups",
                "logstats_run_command_render",
                "logstats_search_exact",
                "logstats_tools",
            )
        ),
        *(
            (
                f"binnacle.ops.watchdog.{name}",
                f"binnacle.companions.watchdog.ops.{name}",
            )
            for name in (
                "context",
                "device_identity",
                "fast",
                "lock",
                "policy",
                "policy_recovery",
                "policy_routes",
                "policy_usb",
                "reporting",
            )
        ),
        (
            "binnacle.system_resource_contracts",
            "binnacle.observability.system_resource_contracts",
        ),
        ("binnacle.watchdog_cli", "binnacle.companions.watchdog.watchdog_cli"),
    ],
)
def test_migrated_facade_is_same_module(legacy: str, canonical: str):
    owned = importlib.import_module(canonical)
    compat = importlib.import_module(legacy)
    assert compat is owned
    assert importlib.import_module(legacy) is owned


def test_files_path_guard_facade_retains_public_functions():
    from binnacle import paths
    from binnacle.features.files import paths as owned

    assert paths.__all__ == ["full_match", "nearby_hint", "resolve_path"]
    for name in paths.__all__:
        assert getattr(paths, name) is getattr(owned, name)


@pytest.mark.parametrize(
    ("legacy_path", "canonical"),
    [
        ("job_manager.py", "binnacle.features.commands.job_manager"),
        ("watchdog_cli.py", "binnacle.companions.watchdog.watchdog_cli"),
    ],
)
def test_legacy_cli_main_guard_dispatches_only_to_stub(
    monkeypatch, legacy_path: str, canonical: str
):
    """Never launch the actual durable job manager or watchdog in a unit test."""
    import runpy
    import sys
    from pathlib import Path
    from types import ModuleType

    calls = []
    stub = ModuleType(canonical)
    stub.__dict__["main"] = lambda: calls.append("stub-only")
    monkeypatch.setitem(sys.modules, canonical, stub)
    wrapper = Path(__file__).resolve().parents[3] / "src" / "binnacle" / legacy_path
    runpy.run_path(str(wrapper), run_name="__main__")
    assert calls == ["stub-only"]
