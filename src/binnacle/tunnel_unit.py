"""Compatibility alias for tunnel-companion-owned tunnel_unit."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.tunnel.tunnel_unit import *
else:
    import sys

    from binnacle.companions.tunnel import tunnel_unit as _impl

    sys.modules[__name__] = _impl
