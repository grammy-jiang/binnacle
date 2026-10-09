"""Exercise relocated public facades without changing per-module coverage floors."""

from __future__ import annotations

import importlib
import importlib.util

import pytest


@pytest.mark.parametrize(
    ("legacy", "canonical"),
    [
        ("binnacle.job_manager", "binnacle.features.commands.job_manager"),
    ],
)
def test_migrated_facade_is_same_module(legacy: str, canonical: str):
    owned = importlib.import_module(canonical)
    compat = importlib.import_module(legacy)
    assert compat is owned
    assert importlib.import_module(legacy) is owned


def test_files_path_guard_canonical_exports():
    from binnacle.features.files import paths

    assert all(
        callable(getattr(paths, name))
        for name in ("full_match", "nearby_hint", "resolve_path")
    )


@pytest.mark.parametrize(
    ("legacy_path", "canonical"),
    [
        ("job_manager.py", "binnacle.features.commands.job_manager"),
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

    # Import the real package and alias before replacing the CLI entry point:
    # this test must exercise both module identity and script dispatch in
    # isolation, regardless of which pytest worker executes it.
    implementation = importlib.import_module(canonical)
    assert (
        importlib.import_module(f"binnacle.{legacy_path.removesuffix('.py')}")
        is implementation
    )
    calls = []
    stub = ModuleType(canonical)
    stub.__dict__["main"] = lambda: calls.append("stub-only")
    monkeypatch.setitem(sys.modules, canonical, stub)
    wrapper = Path(__file__).resolve().parents[3] / "src" / "binnacle" / legacy_path
    runpy.run_path(str(wrapper), run_name="__main__")
    assert calls == ["stub-only"]
