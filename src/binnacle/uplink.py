"""Compatibility alias for binnacle.companions.watchdog.uplink."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.uplink import *
    from binnacle.companions.watchdog.uplink import (
        _SUDO_NOARG_FLAGS as _SUDO_NOARG_FLAGS,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.uplink import (
        _bind_device as _bind_device,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.uplink import (
        _dns_query as _dns_query,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.uplink import (
        _first_a_record as _first_a_record,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.uplink import (
        _last_address as _last_address,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.uplink import (
        _probe_layers as _probe_layers,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.uplink import (
        _run as _run,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.uplink import (
        _skip_name as _skip_name,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.companions.watchdog import uplink as _impl

    sys.modules[__name__] = _impl
