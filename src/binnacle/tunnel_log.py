"""Runtime compatibility alias for tunnel-companion-owned tunnel_log.

The public G5 watchdog contract remains binnacle.tunnel_log.scan_tunnel_log.
Runtime aliasing preserves module identity without a static reverse package edge;
static compatibility is supplied by the .pyi.
"""

import importlib
import sys

_impl = importlib.import_module("binnacle.companions.tunnel.tunnel_log")
sys.modules[__name__] = _impl
