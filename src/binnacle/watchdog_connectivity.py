"""Compatibility alias for watchdog-companion-owned watchdog_connectivity."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.watchdog_connectivity import *
else:
    import sys

    from binnacle.companions.watchdog import watchdog_connectivity as _impl

    sys.modules[__name__] = _impl
