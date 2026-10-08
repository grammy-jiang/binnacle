"""Compatibility alias for tunnel-companion-owned tunnel_cli."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.companions.tunnel.tunnel_cli import *
else:
    import sys

    from binnacle.companions.tunnel import tunnel_cli as _impl

    sys.modules[__name__] = _impl
