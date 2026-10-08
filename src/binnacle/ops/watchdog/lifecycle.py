"""Compatibility alias for binnacle.companions.watchdog.ops.lifecycle."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.ops.lifecycle import *
    from binnacle.companions.watchdog.ops.lifecycle import (
        _run as _run,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.companions.watchdog.ops import lifecycle as _impl

    sys.modules[__name__] = _impl
