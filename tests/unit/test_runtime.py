"""Tests for package/runtime identity values."""

from dataclasses import FrozenInstanceError

import pytest

from binnacle import distribution_version
from binnacle.domain.runtime import PackageIdentity, RuntimeProfile


def test_distribution_version_is_available() -> None:
    assert distribution_version()


def test_package_identity_is_frozen(package_identity: PackageIdentity) -> None:
    with pytest.raises(FrozenInstanceError):
        package_identity.version = "changed"  # type: ignore[misc]


def test_runtime_profile_is_development() -> None:
    assert RuntimeProfile.DEVELOPMENT.value == "development"
