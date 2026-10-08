"""Compatibility alias for binnacle.companions.watchdog.ops.policy."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.ops.policy import *
else:
    import sys

    from binnacle.companions.watchdog.ops import policy as _impl

    sys.modules[__name__] = _impl
