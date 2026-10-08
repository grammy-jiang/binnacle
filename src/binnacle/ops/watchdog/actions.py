"""Compatibility alias for binnacle.companions.watchdog.ops.actions."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.ops.actions import *
    from binnacle.companions.watchdog.ops.actions import (
        _ActionContext as _ActionContext,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.actions import (
        _apply_demote as _apply_demote,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.actions import (
        _apply_reload as _apply_reload,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.actions import (
        _apply_reset as _apply_reset,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.actions import (
        _apply_restore as _apply_restore,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.actions import (
        _apply_usb_reset as _apply_usb_reset,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.actions import (
        _modify_metric as _modify_metric,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.actions import (
        _reapply as _reapply,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.actions import (
        _run as _run,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.companions.watchdog.ops import actions as _impl

    sys.modules[__name__] = _impl
