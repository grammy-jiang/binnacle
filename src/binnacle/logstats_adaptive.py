"""Compatibility alias for observability-owned logstats_adaptive."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.observability.logstats_adaptive import *
else:
    import sys

    from binnacle.observability import logstats_adaptive as _impl

    sys.modules[__name__] = _impl
