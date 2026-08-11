"""Tests for the framework-independent application lifecycle."""

import pytest

from binnacle.application import BinnacleApplication
from binnacle.domain.runtime import PackageIdentity


@pytest.mark.anyio
async def test_application_start_is_idempotent(package_identity: PackageIdentity) -> None:
    application = BinnacleApplication(identity=package_identity)

    await application.start()
    await application.start()

    assert application.is_started
    assert application.identity is package_identity


@pytest.mark.anyio
async def test_application_stop_is_idempotent(package_identity: PackageIdentity) -> None:
    application = BinnacleApplication(identity=package_identity)
    await application.start()

    await application.stop()
    await application.stop()

    assert not application.is_started
