"""Compatibility alias for tunnel-companion-owned tunnel_log."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.tunnel.tunnel_log import *
else:
    import sys

    from binnacle.companions.tunnel import tunnel_log as _impl

    sys.modules[__name__] = _impl
