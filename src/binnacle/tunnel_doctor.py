"""Compatibility alias for tunnel-companion-owned tunnel_doctor."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.tunnel.tunnel_doctor import *
else:
    import sys

    from binnacle.companions.tunnel import tunnel_doctor as _impl

    sys.modules[__name__] = _impl
