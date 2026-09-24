"""Shared opt-in fixtures for integration tests."""

import pytest

from binnacle import jobs as jobstore


@pytest.fixture()
def _short_job_warmup(monkeypatch):
    """Use a short warm-up only in integration modules that opt in."""
    monkeypatch.setattr(jobstore, "WARMUP_S", 0.05)
