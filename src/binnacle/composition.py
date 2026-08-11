"""Explicit application composition root."""

from __future__ import annotations

from dataclasses import dataclass, field

from binnacle import distribution_version
from binnacle.application import BinnacleApplication
from binnacle.config import BinnacleSettings
from binnacle.domain.runtime import PackageIdentity
from binnacle.logging import LoggingRuntime, configure_logging


@dataclass(slots=True)
class ComposedApplication:
    """Resources owned by one composed application."""

    settings: BinnacleSettings
    application: BinnacleApplication
    logging_runtime: LoggingRuntime
    _closed: bool = field(default=False, init=False, repr=False)

    async def close(self) -> None:
        """Stop application and logging resources exactly once."""

        if self._closed:
            return
        self._closed = True
        try:
            await self.application.stop()
        finally:
            self.logging_runtime.close()


def compose_application(*, settings: BinnacleSettings) -> ComposedApplication:
    """Build the minimal application in deterministic dependency order."""

    logging_runtime = configure_logging(settings.logging)
    try:
        identity = PackageIdentity(
            distribution_name="binnacle",
            version=distribution_version(),
        )
        application = BinnacleApplication(identity=identity)
        return ComposedApplication(
            settings=settings,
            application=application,
            logging_runtime=logging_runtime,
        )
    except Exception:
        logging_runtime.close()
        raise
