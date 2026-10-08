"""Compatibility alias for binnacle.companions.watchdog.ops.services."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.ops.services import *
    from binnacle.companions.watchdog.ops.services import (
        _rfc3339_epoch as _rfc3339_epoch,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.services import (
        _run as _run,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.companions.watchdog.ops import services as _impl

    sys.modules[__name__] = _impl
