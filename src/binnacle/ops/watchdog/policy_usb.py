"""Compatibility alias for binnacle.companions.watchdog.ops.policy_usb."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.ops.policy_usb import *
    from binnacle.companions.watchdog.ops.policy_usb import (
        _at_target as _at_target,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.policy_usb import (
        _exhausted as _exhausted,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.policy_usb import (
        _level_text as _level_text,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.policy_usb import (
        _observe_only as _observe_only,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.policy_usb import (
        _plan_repair as _plan_repair,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.policy_usb import (
        _reconcile as _reconcile,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.policy_usb import (
        _repair_allowed as _repair_allowed,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.policy_usb import (
        _rule_for as _rule_for,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.policy_usb import (
        _usb_speed_due as _usb_speed_due,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.companions.watchdog.ops import policy_usb as _impl

    sys.modules[__name__] = _impl
