"""Compatibility alias for binnacle.companions.watchdog.ops.diagnostics."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.ops.diagnostics import *
else:
    import sys

    from binnacle.companions.watchdog.ops import diagnostics as _impl

    sys.modules[__name__] = _impl
