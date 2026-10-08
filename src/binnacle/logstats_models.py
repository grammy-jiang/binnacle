"""Compatibility alias for observability-owned logstats_models."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binnacle.observability.logstats_models import *
else:
    import sys

    from binnacle.observability import logstats_models as _impl

    sys.modules[__name__] = _impl
