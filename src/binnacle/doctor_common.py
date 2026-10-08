"""Compatibility alias for diagnostics-owned doctor_common."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.diagnostics.doctor_common import *
else:
    import sys

    from binnacle.diagnostics import doctor_common as _impl

    sys.modules[__name__] = _impl
