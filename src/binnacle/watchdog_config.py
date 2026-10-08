"""Compatibility alias for watchdog-companion-owned watchdog_config."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.watchdog_config import *
else:
    import sys

    from binnacle.companions.watchdog import watchdog_config as _impl

    sys.modules[__name__] = _impl
