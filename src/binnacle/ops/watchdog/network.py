"""Compatibility alias for binnacle.companions.watchdog.ops.network."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.ops.network import *
    from binnacle.companions.watchdog.ops.network import (
        _run as _run,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.network import (
        _split_terse as _split_terse,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.companions.watchdog.ops import network as _impl

    sys.modules[__name__] = _impl
