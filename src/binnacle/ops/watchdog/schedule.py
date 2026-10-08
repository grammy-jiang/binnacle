"""Compatibility alias for binnacle.companions.watchdog.ops.schedule."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.ops.schedule import *
    from binnacle.companions.watchdog.ops.schedule import (
        _may_reset as _may_reset,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.schedule import (
        _prefer_due as _prefer_due,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.schedule import (
        _reload_due as _reload_due,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.schedule import (
        _repairs_in_episode as _repairs_in_episode,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.schedule import (
        _usb_reset_due as _usb_reset_due,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.schedule import (
        _usb_speed_due as _usb_speed_due,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.companions.watchdog.ops import schedule as _impl

    sys.modules[__name__] = _impl
