"""Compatibility alias for watchdog-companion-owned watchdog_doctor."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.watchdog_doctor import *
else:
    import sys

    from binnacle.companions.watchdog import watchdog_doctor as _impl

    sys.modules[__name__] = _impl
