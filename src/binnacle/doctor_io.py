"""Compatibility alias for diagnostics-owned doctor_io."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.diagnostics.doctor_io import *
    from binnacle.diagnostics.doctor_io import (
        _tail_lines as _tail_lines,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.diagnostics import doctor_io as _impl

    sys.modules[__name__] = _impl
