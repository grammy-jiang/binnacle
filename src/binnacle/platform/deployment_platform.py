"""Compatibility entrypoints; host choice belongs only to platform.composition."""

from binnacle.platform.composition import (
    create_linux_provisioner,
    create_runtime_paths,
    create_service_controller,
    create_service_inspector,
    create_service_log_source,
)

__all__ = (
    "create_linux_provisioner",
    "create_runtime_paths",
    "create_service_controller",
    "create_service_inspector",
    "create_service_log_source",
)
