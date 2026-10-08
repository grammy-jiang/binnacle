"""Compatibility alias for observability-owned logstats_io."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.observability.logstats_io import *
else:
    import sys

    from binnacle.observability import logstats_io as _impl

    sys.modules[__name__] = _impl
