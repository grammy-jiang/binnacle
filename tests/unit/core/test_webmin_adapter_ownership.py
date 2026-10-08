"""G6 Webmin adapter location and backwards-compatible import identity."""

import sys
from importlib import import_module


def test_public_webmin_facade_is_owned_adapter():
    facade = import_module("binnacle.webminstats")
    owned = import_module("binnacle.observability.linux.webminstats")

    assert facade is owned
    assert sys.modules["binnacle.webminstats"] is owned


def test_resource_history_factory_uses_observability_adapter():
    from binnacle.observability.linux.webminstats import WebminSystemResourceHistory
    from binnacle.observability.system_resource_history import (
        create_system_resource_history,
    )

    assert isinstance(create_system_resource_history(), WebminSystemResourceHistory)


def test_compatibility_monkeypatch_reaches_owned_module(monkeypatch):
    facade = import_module("binnacle.webminstats")
    owned = import_module("binnacle.observability.linux.webminstats")
    sentinel = object()

    monkeypatch.setattr(facade, "HISTORY_DIR", sentinel)
    assert owned.HISTORY_DIR is sentinel
