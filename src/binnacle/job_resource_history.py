"""Compatibility alias for Commands-owned job_resource_history."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.features.commands.job_resource_history import *
    from binnacle.features.commands.job_resource_history import (
        _prune as _prune,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.features.commands import job_resource_history as _impl

    sys.modules[__name__] = _impl
