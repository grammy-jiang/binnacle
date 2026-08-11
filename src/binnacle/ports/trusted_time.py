"""Trusted-time observation boundary."""

from __future__ import annotations

from typing import Protocol

from binnacle.domain.trusted_time import TrustedTimeSnapshot


class TrustedTimeSource(Protocol):
    async def snapshot(self) -> TrustedTimeSnapshot: ...
