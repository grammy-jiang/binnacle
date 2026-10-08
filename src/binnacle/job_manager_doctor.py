"""Legacy module identity for diagnostics-owned job manager doctor."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.diagnostics.job_manager_doctor import *
else:
    import sys

    from binnacle.diagnostics import job_manager_doctor as _impl

    sys.modules[__name__] = _impl
