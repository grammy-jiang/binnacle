"""Compatibility alias for binnacle.companions.watchdog.ops.fast."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.ops.fast import *
    from binnacle.companions.watchdog.ops.fast import (
        _may_reset as _may_reset,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.fast import (
        _run as _run,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.fast import (
        _still_safe as _still_safe,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.companions.watchdog.ops import fast as _impl

    sys.modules[__name__] = _impl
