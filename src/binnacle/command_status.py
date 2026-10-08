"""Compatibility alias for the Commands-owned status module."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.features.commands.command_status import *
    from binnacle.features.commands.command_status import (
        _wait_for_exit as _wait_for_exit,  # noqa: PLC0414
    )
else:
    import sys

    from binnacle.features.commands import command_status as _impl

    sys.modules[__name__] = _impl
