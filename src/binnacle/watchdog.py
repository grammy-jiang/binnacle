"""Compatibility alias for watchdog-companion-owned watchdog."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.watchdog import *
    from binnacle.companions.watchdog.watchdog import (
        _log_issues as _log_issues,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.watchdog import (
        _rfc3339_epoch as _rfc3339_epoch,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.watchdog import (
        _split_terse as _split_terse,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.watchdog import (
        _still_safe as _still_safe,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.companions.watchdog import watchdog as _impl

    sys.modules[__name__] = _impl
