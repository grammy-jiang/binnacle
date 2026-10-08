"""Compatibility alias for observability-owned logstats_tools."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.observability.logstats_tools import *
else:
    import sys

    from binnacle.observability import logstats_tools as _impl

    sys.modules[__name__] = _impl
