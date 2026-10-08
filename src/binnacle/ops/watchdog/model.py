"""Compatibility alias for binnacle.companions.watchdog.ops.model."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.ops.model import *
    from binnacle.companions.watchdog.ops.model import (
        _load_identity as _load_identity,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.companions.watchdog.ops import model as _impl

    sys.modules[__name__] = _impl
