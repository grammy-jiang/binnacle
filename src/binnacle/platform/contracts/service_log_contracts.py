"""Platform-neutral service-log acquisition contract."""

from collections.abc import Sequence
from typing import Protocol


class ServiceLogError(RuntimeError):
    """The platform log source could not satisfy a requested read."""


class ServiceLogSource(Protocol):
    """Read raw service logs over semantic epoch windows."""

    def read_window(
        self,
        services: Sequence[str],
        since_epoch: float,
        until_epoch: float | None = None,
    ) -> str: ...
