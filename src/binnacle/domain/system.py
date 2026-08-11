"""Framework-independent bounded system-inspection values."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SystemSection(StrEnum):
    """Reviewed bounded sections exposed by ``system_inspect``."""

    OS = "os"
    KERNEL = "kernel"
    ARCHITECTURE = "architecture"
    UPTIME = "uptime"
    CPU = "cpu"
    MEMORY = "memory"
    FILESYSTEMS = "filesystems"
    BINNACLE_SERVICE = "binnacle_service"


SYSTEM_SECTION_ORDER = tuple(SystemSection)
DEFAULT_SYSTEM_SECTIONS = (
    SystemSection.OS,
    SystemSection.KERNEL,
    SystemSection.ARCHITECTURE,
    SystemSection.UPTIME,
    SystemSection.CPU,
    SystemSection.MEMORY,
)


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    """One-way-derived stable local device identity."""

    device_id: str


@dataclass(frozen=True, slots=True)
class CpuInfo:
    count: int


@dataclass(frozen=True, slots=True)
class MemoryInfo:
    total_bytes: int
    available_bytes: int


@dataclass(frozen=True, slots=True)
class FilesystemInfo:
    mount_point: str
    filesystem_type: str
    source: str | None
    total_bytes: int
    available_bytes: int


@dataclass(frozen=True, slots=True)
class BinnacleServiceInfo:
    state: str


@dataclass(frozen=True, slots=True)
class InspectionWarning:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class SystemSnapshot:
    """Truthful snapshot of exactly the requested bounded sections."""

    hostname: str
    returned_sections: tuple[SystemSection, ...]
    os_summary: str | None = None
    kernel: str | None = None
    architecture: str | None = None
    uptime_seconds: int | None = None
    cpu: CpuInfo | None = None
    memory: MemoryInfo | None = None
    filesystems: tuple[FilesystemInfo, ...] | None = None
    binnacle_service: BinnacleServiceInfo | None = None
    warnings: tuple[InspectionWarning, ...] = ()


class InspectionError(RuntimeError):
    """A bounded requested fact could not be collected truthfully."""


class DeviceIdentityError(RuntimeError):
    """No stable local identity source was available."""
