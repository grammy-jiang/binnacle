"""Compatibility alias for binnacle.companions.watchdog.ops.config."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.ops.config import *
else:
    import sys

    from binnacle.companions.watchdog.ops import config as _impl

    sys.modules[__name__] = _impl
