"""Compatibility alias for binnacle.companions.watchdog.ops.cycle."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.ops.cycle import *
    from binnacle.companions.watchdog.ops.cycle import (
        _execute_actions as _execute_actions,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.cycle import (
        _log_decision as _log_decision,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.cycle import (
        _log_probes as _log_probes,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.cycle import (
        _observe as _observe,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.cycle import (
        _Observed as _Observed,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.cycle import (
        _pause_state as _pause_state,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.cycle import (
        _preferences as _preferences,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.cycle import (
        _record_transitions as _record_transitions,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.cycle import (
        _run as _run,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.ops.cycle import (
        _still_safe as _still_safe,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.companions.watchdog.ops import cycle as _impl

    sys.modules[__name__] = _impl
