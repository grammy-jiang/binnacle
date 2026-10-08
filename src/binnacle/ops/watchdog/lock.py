"""Compatibility alias for binnacle.companions.watchdog.ops.lock."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.ops.lock import *
else:
    import sys

    from binnacle.companions.watchdog.ops import lock as _impl

    sys.modules[__name__] = _impl
