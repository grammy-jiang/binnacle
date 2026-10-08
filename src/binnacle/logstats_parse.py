"""Compatibility alias for observability-owned logstats_parse."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.observability.logstats_parse import *
else:
    import sys

    from binnacle.observability import logstats_parse as _impl

    sys.modules[__name__] = _impl
