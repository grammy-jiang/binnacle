"""Compatibility entrypoints delegating OS selection to one composition boundary."""

from binnacle.platform.composition import (
    create_process_backend,
    create_resource_accounting,
)

__all__ = ("create_process_backend", "create_resource_accounting")
