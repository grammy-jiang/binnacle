"""Compatibility alias for binnacle.companions.watchdog.ops.maintenance."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.ops.maintenance import *
else:
    import sys

    from binnacle.companions.watchdog.ops import maintenance as _impl

    sys.modules[__name__] = _impl
