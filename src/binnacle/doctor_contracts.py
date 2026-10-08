"""Compatibility alias for diagnostics-owned doctor_contracts."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.diagnostics.doctor_contracts import *
else:
    import sys

    from binnacle.diagnostics import doctor_contracts as _impl

    sys.modules[__name__] = _impl
