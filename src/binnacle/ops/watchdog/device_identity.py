"""Compatibility alias for binnacle.companions.watchdog.ops.device_identity."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.ops.device_identity import *
    from binnacle.companions.watchdog.ops.device_identity import (
        _bind as _bind,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.device_identity import (
        _drop_transient as _drop_transient,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.device_identity import (
        _kind as _kind,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.device_identity import (
        _put as _put,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.device_identity import (
        _take as _take,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.companions.watchdog.ops import device_identity as _impl

    sys.modules[__name__] = _impl
