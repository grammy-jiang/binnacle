"""Compatibility alias for binnacle.companions.watchdog.ops.policy_routes."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.ops.policy_routes import *
    from binnacle.companions.watchdog.ops.policy_routes import (
        _may_reset as _may_reset,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.policy_routes import (
        _reload_due as _reload_due,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.policy_routes import (
        _usb_reset_due as _usb_reset_due,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.companions.watchdog.ops import policy_routes as _impl

    sys.modules[__name__] = _impl
