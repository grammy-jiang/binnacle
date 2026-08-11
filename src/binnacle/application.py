"""Framework-independent application lifecycle."""

from binnacle.domain.runtime import PackageIdentity


class BinnacleApplication:
    """Minimal idempotent lifecycle for the Phase 1 application."""

    def __init__(self, *, identity: PackageIdentity) -> None:
        self._identity = identity
        self._started = False

    @property
    def identity(self) -> PackageIdentity:
        """Return this process's package identity."""

        return self._identity

    @property
    def is_started(self) -> bool:
        """Return whether the application lifecycle is started."""

        return self._started

    async def start(self) -> None:
        """Start the application once."""

        self._started = True

    async def stop(self) -> None:
        """Stop the application if it is running."""

        self._started = False
