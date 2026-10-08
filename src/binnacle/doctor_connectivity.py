"""Compatibility alias for diagnostics-owned endpoint doctor."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.diagnostics.doctor_connectivity import *
    from binnacle.diagnostics.doctor_connectivity import (
        _post_initialize as _post_initialize,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.diagnostics import doctor_connectivity as _impl

    sys.modules[__name__] = _impl
