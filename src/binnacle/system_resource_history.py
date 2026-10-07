"""Explicit, lazy composition of the optional system resource history reader."""

from binnacle.system_resource_contracts import SystemResourceHistory


def create_system_resource_history() -> SystemResourceHistory:
    from binnacle.webminstats import WebminSystemResourceHistory

    return WebminSystemResourceHistory()
