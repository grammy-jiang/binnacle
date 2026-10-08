"""Compatibility alias for binnacle.companions.watchdog.ops.reporting."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.ops.reporting import *
    from binnacle.companions.watchdog.ops.reporting import (
        _log_issues as _log_issues,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.companions.watchdog.ops import reporting as _impl

    sys.modules[__name__] = _impl
