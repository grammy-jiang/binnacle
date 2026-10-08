"""Compatibility alias for Commands-owned job_output."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.features.commands.job_output import *
    from binnacle.features.commands.job_output import (
        _elision_marker as _elision_marker,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.features.commands import job_output as _impl

    sys.modules[__name__] = _impl
