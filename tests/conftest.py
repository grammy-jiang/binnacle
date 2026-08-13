"""Shared test fixtures for the executable skeleton."""

from pathlib import Path

import pytest

from binnacle.application import BinnacleApplication, CompatibilityUseCases
from binnacle.contracts import ContractRegistry
from binnacle.domain.mcp import (
    CompatibilityObservation,
    CompatibilityProfileSnapshot,
)
from binnacle.domain.runtime import BuildIdentity, PackageIdentity
from binnacle.domain.system import (
    BinnacleServiceInfo,
    CpuInfo,
    DeviceIdentity,
    FilesystemInfo,
    MemoryInfo,
    SystemSection,
    SystemSnapshot,
)


class FakeDeviceIdentityProvider:
    """Deterministic device port for application/transport tests."""

    def get_device_identity(self) -> DeviceIdentity:
        return DeviceIdentity(device_id="device_fixture")


class FakeSystemInspector:
    """Return complete deterministic values for requested sections."""

    def __init__(self) -> None:
        self.requests: list[tuple[SystemSection, ...]] = []

    async def inspect(self, sections: tuple[SystemSection, ...]) -> SystemSnapshot:
        self.requests.append(sections)
        selected = set(sections)
        return SystemSnapshot(
            hostname="fixture-pi",
            returned_sections=sections,
            os_summary="Fixture Linux" if SystemSection.OS in selected else None,
            kernel="6.12-fixture" if SystemSection.KERNEL in selected else None,
            architecture="aarch64" if SystemSection.ARCHITECTURE in selected else None,
            uptime_seconds=123 if SystemSection.UPTIME in selected else None,
            cpu=CpuInfo(count=4) if SystemSection.CPU in selected else None,
            memory=MemoryInfo(total_bytes=1024, available_bytes=512)
            if SystemSection.MEMORY in selected
            else None,
            filesystems=(
                FilesystemInfo(
                    mount_point="/",
                    filesystem_type="ext4",
                    source="/dev/root",
                    total_bytes=4096,
                    available_bytes=2048,
                ),
            )
            if SystemSection.FILESYSTEMS in selected
            else None,
            binnacle_service=BinnacleServiceInfo(state="unknown")
            if SystemSection.BINNACLE_SERVICE in selected
            else None,
        )


class FakeCompatibilityProfileReader:
    """Static truthful no-live-host compatibility baseline."""

    def read(self) -> CompatibilityProfileSnapshot:
        return CompatibilityProfileSnapshot(
            profile_version="1.3.0",
            observed_protocol_revision=None,
            observations=(
                CompatibilityObservation(
                    axis="protocol_revision",
                    status="not-tested",
                    summary="No real host evidence.",
                ),
            ),
            evidence_bundle_sha256=None,
            limitations=("Local fixture evidence only.",),
        )


@pytest.fixture
def anyio_backend() -> str:
    """Exercise async tests on the supported standard asyncio backend."""

    return "asyncio"


@pytest.fixture
def repo_root() -> Path:
    """Return the checked-out repository root for frozen-source tests."""

    return Path(__file__).resolve().parents[1]


@pytest.fixture
def package_identity() -> PackageIdentity:
    """Return a deterministic package identity for lifecycle tests."""

    return PackageIdentity(distribution_name="binnacle", version="0.1.0.dev0")


@pytest.fixture
def contract_registry() -> ContractRegistry:
    """Load the checked-in generated compatibility-core registry."""

    return ContractRegistry.load()


@pytest.fixture
def fake_system_inspector() -> FakeSystemInspector:
    return FakeSystemInspector()


@pytest.fixture
def compatibility_use_cases(
    contract_registry: ContractRegistry,
    fake_system_inspector: FakeSystemInspector,
) -> CompatibilityUseCases:
    return CompatibilityUseCases(
        build_identity=BuildIdentity(version="0.1.0.dev0", build_sha256="a" * 64),
        device_identity_provider=FakeDeviceIdentityProvider(),
        system_inspector=fake_system_inspector,
        compatibility_reader=FakeCompatibilityProfileReader(),
        contracts=contract_registry,
    )


@pytest.fixture
def phase2_application(
    package_identity: PackageIdentity,
    contract_registry: ContractRegistry,
    compatibility_use_cases: CompatibilityUseCases,
) -> BinnacleApplication:
    return BinnacleApplication(
        identity=package_identity,
        contracts=contract_registry,
        compatibility=compatibility_use_cases,
    )
