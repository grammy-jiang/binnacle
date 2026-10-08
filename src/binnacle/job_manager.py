"""Compatibility alias for the Commands-owned durable job manager."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.features.commands.job_manager import *
    from binnacle.features.commands.job_manager import (
        _boot_id as _boot_id,  # noqa: PLC0414
    )
    from binnacle.features.commands.job_manager import (
        _notify_systemd_ready as _notify_systemd_ready,  # noqa: PLC0414
    )
elif __name__ == "__main__":
    from binnacle.features.commands.job_manager import main

    main()
else:
    import sys

    from binnacle.features.commands import job_manager as _impl

    sys.modules[__name__] = _impl
