"""Compatibility alias for deployment-owned units."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.deployment.units import *
else:
    import sys

    from binnacle.deployment import units as _impl

    sys.modules[__name__] = _impl
