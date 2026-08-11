"""Sanitized compatibility-profile port."""

from typing import Protocol

from binnacle.domain.mcp import CompatibilityProfileSnapshot


class CompatibilityProfileReader(Protocol):
    def read(self) -> CompatibilityProfileSnapshot: ...
