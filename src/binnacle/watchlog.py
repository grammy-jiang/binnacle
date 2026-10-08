"""Compatibility alias for watchdog-companion-owned watchlog."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.watchlog import *
    from binnacle.companions.watchdog.watchlog import (
        _rfc3339 as _rfc3339,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.watchlog import (
        _short as _short,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.companions.watchdog import watchlog as _impl

    sys.modules[__name__] = _impl
