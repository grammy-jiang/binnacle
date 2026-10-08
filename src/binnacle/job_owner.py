"""Compatibility alias for Commands-owned job_owner."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.features.commands.job_owner import *
else:
    import sys

    from binnacle.features.commands import job_owner as _impl

    sys.modules[__name__] = _impl
