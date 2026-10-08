"""Compatibility alias for deployment-owned server_unit."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.deployment.server_unit import *
else:
    import sys

    from binnacle.deployment import server_unit as _impl

    sys.modules[__name__] = _impl
