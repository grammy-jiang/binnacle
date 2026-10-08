"""Compatibility alias for Commands-owned job_client."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.features.commands.job_client import *
else:
    import sys

    from binnacle.features.commands import job_client as _impl

    sys.modules[__name__] = _impl
