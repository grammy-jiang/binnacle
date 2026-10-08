"""Runtime compatibility alias for tunnel-companion-owned tunnel_unit.

The public G5 contract remains binnacle.tunnel_unit.TUNNEL_UNIT. This bridge uses
a runtime import so the legacy compatibility name does not create a static reverse
edge in the converged package graph. Static compatibility is supplied by the .pyi.
"""

import importlib
import sys

_impl = importlib.import_module("binnacle.companions.tunnel.tunnel_unit")
sys.modules[__name__] = _impl
