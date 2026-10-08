"""Compatibility alias for binnacle.companions.watchdog.ops.context."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.ops.context import *
    from binnacle.companions.watchdog.ops.context import (
        _repairs_in_episode as _repairs_in_episode,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.companions.watchdog.ops import context as _impl

    sys.modules[__name__] = _impl
