"""Shared opt-in fixtures for integration tests."""

import pytest

from binnacle.features.commands import jobs as jobstore


@pytest.fixture()
def _short_job_warmup(monkeypatch):
    """Use a short warm-up only in integration modules that opt in."""
    monkeypatch.setattr(jobstore, "WARMUP_S", 0.05)


@pytest.fixture
def run_policy(monkeypatch):
    """Build the real root with an explicitly configured Commands child."""
    from binnacle import server

    factory = server.create_commands_server

    def configure(settings):
        def commands(**kwargs):
            return factory(**{**kwargs, "run_settings": settings})

        monkeypatch.setattr(server, "create_commands_server", commands)
        monkeypatch.setattr(server, "mcp", server.create_server())

    return configure
