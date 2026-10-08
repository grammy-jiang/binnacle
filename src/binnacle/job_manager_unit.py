"""Compatibility alias for deployment-owned job_manager_unit."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.deployment.job_manager_unit import *
else:
    import sys

    from binnacle.deployment import job_manager_unit as _impl

    sys.modules[__name__] = _impl
