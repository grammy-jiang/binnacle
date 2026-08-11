"""Bounded system-inspection port."""

from typing import Protocol

from binnacle.domain.system import SystemSection, SystemSnapshot


class SystemInspector(Protocol):
    async def inspect(self, sections: tuple[SystemSection, ...]) -> SystemSnapshot: ...
