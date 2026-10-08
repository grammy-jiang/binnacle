"""Compatibility alias for diagnostics-owned doctor_render."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.diagnostics.doctor_render import *
else:
    import sys

    from binnacle.diagnostics import doctor_render as _impl

    sys.modules[__name__] = _impl
