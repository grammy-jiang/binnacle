"""Compatibility module alias for diagnostics-owned doctor_provenance."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.diagnostics.doctor_provenance import *
else:
    import sys

    from binnacle.diagnostics import doctor_provenance as _impl

    sys.modules[__name__] = _impl
