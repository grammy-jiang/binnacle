"""Shared test fixtures for the executable skeleton."""

import pytest

from binnacle.domain.runtime import PackageIdentity


@pytest.fixture
def anyio_backend() -> str:
    """Exercise async tests on the supported standard asyncio backend."""

    return "asyncio"


@pytest.fixture
def package_identity() -> PackageIdentity:
    """Return a deterministic package identity for lifecycle tests."""

    return PackageIdentity(distribution_name="binnacle", version="0.1.0.dev0")
