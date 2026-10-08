"""Compatibility alias for binnacle.companions.watchdog.watchdog_cli."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.watchdog.watchdog_cli import *
    from binnacle.companions.watchdog.watchdog_cli import (
        _link_policies as _link_policies,  # noqa: PLC0414
    )
    from binnacle.companions.watchdog.watchdog_cli import (
        _policy_from as _policy_from,  # noqa: PLC0414
    )
elif __name__ == "__main__":
    from binnacle.companions.watchdog.watchdog_cli import main

    main()
else:
    import sys

    from binnacle.companions.watchdog import watchdog_cli as _impl

    sys.modules[__name__] = _impl
