"""Runtime identity values owned by the domain layer."""

from dataclasses import dataclass
from enum import StrEnum


class RuntimeProfile(StrEnum):
    """Supported runtime profiles in the project skeleton."""

    DEVELOPMENT = "development"


@dataclass(frozen=True, slots=True)
class PackageIdentity:
    """Stable package identity for one application process."""

    distribution_name: str
    version: str
