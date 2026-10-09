"""Canonical Linux Webmin adapter ownership without a legacy module alias."""

from importlib import import_module


def test_canonical_webmin_adapter_import_identity():
    owned = import_module("binnacle.observability.linux.webminstats")
    assert owned.__name__ == "binnacle.observability.linux.webminstats"
    assert hasattr(owned, "WebminSystemResourceHistory")


def test_resource_history_factory_uses_observability_adapter():
    from binnacle.observability.linux.webminstats import WebminSystemResourceHistory
    from binnacle.observability.system_resource_history import (
        create_system_resource_history,
    )

    assert isinstance(create_system_resource_history(), WebminSystemResourceHistory)


def test_canonical_webmin_monkeypatch_reaches_factory_module(monkeypatch):
    owned = import_module("binnacle.observability.linux.webminstats")
    sentinel = object()

    monkeypatch.setattr(owned, "HISTORY_DIR", sentinel)
    assert (
        import_module("binnacle.observability.linux.webminstats").HISTORY_DIR
        is sentinel
    )
