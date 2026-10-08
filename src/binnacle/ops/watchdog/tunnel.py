"""Compatibility alias for binnacle.companions.watchdog.ops.tunnel."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.ops.tunnel import *
    from binnacle.companions.watchdog.ops.tunnel import (
        _log_decision as _log_decision,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.tunnel import (
        _log_issues as _log_issues,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.tunnel import (
        _run as _run,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.companions.watchdog.ops import tunnel as _impl

    sys.modules[__name__] = _impl
