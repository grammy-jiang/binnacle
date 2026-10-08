"""Compatibility alias for observability-owned system_resource_history."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.observability.system_resource_history import *
else:
    import sys

    from binnacle.observability import system_resource_history as _impl

    sys.modules[__name__] = _impl
