"""Deterministic Python logging and structlog configuration."""

from __future__ import annotations

import logging as stdlib_logging
import sys
from dataclasses import dataclass, field

import structlog

from binnacle.config import LoggingSettings


@dataclass(slots=True)
class LoggingRuntime:
    """Own the handler installed by one logging configuration."""

    handler: stdlib_logging.Handler
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        """Remove and close the owned handler exactly once."""

        if self._closed:
            return
        self._closed = True
        root_logger = stdlib_logging.getLogger()
        if self.handler in root_logger.handlers:
            root_logger.removeHandler(self.handler)
        self.handler.close()


_active_runtime: LoggingRuntime | None = None


def configure_logging(settings: LoggingSettings) -> LoggingRuntime:
    """Replace process logging with one deterministic structlog pipeline."""

    global _active_runtime

    if _active_runtime is not None:
        _active_runtime.close()

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        structlog.processors.format_exc_info,
    ]
    renderer: structlog.types.Processor
    if settings.format == "json":
        renderer = structlog.processors.JSONRenderer(sort_keys=True)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    handler = stdlib_logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root_logger = stdlib_logging.getLogger()
    for existing_handler in tuple(root_logger.handlers):
        root_logger.removeHandler(existing_handler)
        existing_handler.close()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.level)

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )

    runtime = LoggingRuntime(handler=handler)
    _active_runtime = runtime
    return runtime
