"""Compatibility alias for observability-owned system_resource_contracts."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.observability.system_resource_contracts import *
else:
    import sys

    from binnacle.observability import system_resource_contracts as _impl

    sys.modules[__name__] = _impl
