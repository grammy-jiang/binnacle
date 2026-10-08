"""Compatibility identity alias for diagnostics-owned job doctors."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.diagnostics.doctor_jobs import *
else:
    import sys

    from binnacle.diagnostics import doctor_jobs as _impl

    sys.modules[__name__] = _impl
