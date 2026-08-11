"""Tests for the closed bounded system-inspection vocabulary."""

from binnacle.domain.system import (
    DEFAULT_SYSTEM_SECTIONS,
    SYSTEM_SECTION_ORDER,
    DeviceIdentityError,
    InspectionError,
    SystemSection,
)


def test_system_section_order_is_exact_and_closed() -> None:
    assert SYSTEM_SECTION_ORDER == (
        SystemSection.OS,
        SystemSection.KERNEL,
        SystemSection.ARCHITECTURE,
        SystemSection.UPTIME,
        SystemSection.CPU,
        SystemSection.MEMORY,
        SystemSection.FILESYSTEMS,
        SystemSection.BINNACLE_SERVICE,
    )


def test_default_sections_exclude_expensive_optional_sections() -> None:
    assert SYSTEM_SECTION_ORDER[:6] == DEFAULT_SYSTEM_SECTIONS
    assert SystemSection.FILESYSTEMS not in DEFAULT_SYSTEM_SECTIONS
    assert SystemSection.BINNACLE_SERVICE not in DEFAULT_SYSTEM_SECTIONS


def test_domain_error_types_are_explicit() -> None:
    assert issubclass(InspectionError, RuntimeError)
    assert issubclass(DeviceIdentityError, RuntimeError)
