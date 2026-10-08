"""Compatibility alias for observability-owned logstats_search_exact."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.observability.logstats_search_exact import *
else:
    import sys

    from binnacle.observability import logstats_search_exact as _impl

    sys.modules[__name__] = _impl
